from pytube import YouTube, Playlist
from ffmpy import FFmpeg
from os.path import exists
from os import makedirs, remove, environ
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import xml.etree.ElementTree as ElementTree
from html import unescape
import time
import math
import logging

MAX_PROCESS_WORKERS_KEY="MAX_PROCESS_WORKERS"
base_path = environ.get("YT_DOWNLOADER_PATH")
max_process_workers = int(environ.get(MAX_PROCESS_WORKERS_KEY)) if MAX_PROCESS_WORKERS_KEY in environ else 4
args = []

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def replace_illegal_chars(starting, illegal_chars=["|"]):
    current_value = starting
    for char in illegal_chars:
        current_value = current_value.replace(char, "")
    return current_value

def get_folder_path(folder_name):
    if(folder_name):
        return "%s/%s" % (base_path, folder_name)
    else:
        return base_path

def make_download_folder(folder_name):
    path = get_folder_path(folder_name)
    if not exists(path):
        logger.info("MAKING DIRECTORY " + str(path))
        makedirs(path)

def download_playlist(url, options):
    (_, __, should_convert_mp3) = options
    playlist = Playlist(url)
    logger.info(playlist.title)
    folder_name = replace_illegal_chars(playlist.title)
    make_download_folder(folder_name)
    logger.debug(playlist)
    logger.debug(f"Playlist length: {len(playlist.video_urls)}")
    with ThreadPoolExecutor() as t:
        mapped = t.map(get_video_from_url, playlist.video_urls)
        mapped = [(item, folder_name, options) for item in mapped]
    with ProcessPoolExecutor(max_workers=max_process_workers) as t:
        mapped = t.map(download_video_direct, mapped)
        mapped = [item for item in mapped]
    logger.info(mapped)
    if should_convert_mp3:
        with ThreadPoolExecutor() as t:
            mapped = t.map(convert_to_mp3, mapped)

def get_video_from_url(video):
    try:
        video = YouTube(video)
        return video
    except Exception:
        return None

def float_to_srt_time_format(d: float) -> str:
    fraction, whole = math.modf(d)
    time_fmt = time.strftime("%H:%M:%S,", time.gmtime(whole))
    ms = f"{fraction:.3f}".replace("0.", "")
    return time_fmt + ms

def convert_subtitles_to_srt(xml):
    segments = []
    root = ElementTree.fromstring(xml).find('body')
    for i, child in enumerate(list(root)):
        text = child.text or ""
        for s_tag in child:
            text += s_tag.text
        caption = unescape(text.replace("\n", " ").replace("  ", " "),)
        try:
            duration = float(child.attrib["d"])/1000
        except KeyError:
            duration = 0.0
        start = float(child.attrib["t"])/1000
        end = start + duration
        sequence_number = i + 1  # convert from 0-indexed to 1.
        line = "{seq}\n{start} --> {end}\n{text}\n".format(
            seq=sequence_number,
            start=float_to_srt_time_format(start),
            end=float_to_srt_time_format(end),
            text=caption,
        )
        segments.append(line)
    return "\n".join(segments).strip()

def download_video_direct(args):
    (video, folder_name, options) = args
    (should_download_video, should_download_audio, _) = options
    destination_folder_path=get_folder_path(folder_name)
    try:
        logger.info("Downloading Video: %s" % video.title)
        highest_quality_video_stream = get_highest_quality_video_stream(video)
        logger.debug("Highest Quality Video Stream: " + str(highest_quality_video_stream))
        highest_quality_audio_stream = get_highest_quality_audio_stream(video)
        logger.debug("Highest Quality Audio Stream: " + str(highest_quality_audio_stream))
        logger.info("Downloading Streams...")
        video_res = highest_quality_video_stream.download(skip_existing=True, output_path=destination_folder_path, filename_prefix="__VIDEO__", max_retries=10) if (should_download_video) else None
        logger.info("Video stream downloaded... You're like most of the way there!")
        audio_res = highest_quality_audio_stream.download(skip_existing=True, output_path=destination_folder_path, filename_prefix="__AUDIO__", max_retries=10) if (should_download_audio) else None
        subtitle_file_path=None
        english_captions = video.captions['en'] if "en" in video.captions else None
        logger.info("Streams downloaded! Don't accidentally cross them!!")

        if(english_captions != None):
            try:
                srt_captions = convert_subtitles_to_srt(english_captions.xml_captions)
                subtitle_file_path = video_res.replace("__VIDEO__", "__SUBTITLES__").replace(".mp4", ".srt")
                logger.debug(subtitle_file_path)
                with open(subtitle_file_path, "w") as f:
                    f.write(srt_captions)
            except Exception as ex:
                logger.info("Generating subtitles did a bad...")
                logger.info(str(ex))
        if(video_res and audio_res):
            output_path = video_res.replace("__VIDEO__", "")
            merge_audio_and_video(video_res, audio_res, subtitle_file_path, output_path)
            remove(video_res)
            remove(audio_res)
            if(subtitle_file_path):
                remove(subtitle_file_path)
            return output_path
        elif(audio_res):
            return audio_res
        else:
            return video_res
    except Exception as ex:
        logger.error(f"Error when downloading video: {video.title}... Details: {ex}")
        return None

def download_video(url, options):
    (should_download_video, should_download_audio, should_convert_mp3) = options
    video = YouTube(url)
    res = download_video_direct((video, None, options))
    if(should_convert_mp3):
        convert_to_mp3(res)
        if(not should_download_video and should_download_audio):
            remove(res)

def get_highest_quality_video_stream(video):
    relevant_streams = video.streams.filter(
        only_video=True, progressive=False)
    return relevant_streams.first()

def get_highest_quality_audio_stream(video):
    webm_stream = video.streams.get_audio_only("webm")
    return webm_stream if webm_stream else video.streams.get_audio_only()

def print_streams_line_by_line(streams):
    for stream in streams:
        logger.info(stream)

def convert_to_mp3(filePath):
    logger.info("Converting %s" % filePath)
    cmd = FFmpeg(
        global_options="-loglevel quiet -y",
        inputs={filePath: None},
        outputs={filePath.replace(".mp4", ".mp3").replace(".webm", ".mp3"): None}
    )
    cmd.run()
    return cmd.cmd

def merge_audio_and_video(video_path, audio_path, subtitle_path, output_path):
    logger.info("Crossing the streams...")
    logger.debug("Creating merged file: %s" % output_path)
    inputs = {video_path: None, audio_path: None}
    if(subtitle_path != None):
        inputs[subtitle_path] = None

    global_options = "-loglevel quiet -y"

    if "FFMPEG_GLOBAL_FLAGS" in environ:
        flags = environ["FFMPEG_GLOBAL_FLAGS"]
        global_options = global_options + f" {flags}"

    logger.info(global_options)
    cmd = FFmpeg(
        global_options=global_options,
        inputs=inputs,
        outputs={output_path: "-c:v copy -c:a copy -c:s mov_text"}
    )
    try:
        cmd.run()
    except Exception as ex:
        logger.error("Error when merging...")
        logger.error(ex)

def download(url, content_mask):
    options = set_options(content_mask)
    if "/playlist?list=" in url:
        download_playlist(url, options)
    elif "/watch?v=" in url:
        download_video(url, options)
    else:
        logger.info("Please provide a valid Youtube Link.")


def set_options(mask):
    should_download_audio = False
    should_download_video = False
    should_convert_mp3 = False

    if(mask == "ALL"):
        should_download_video = True
        should_download_audio = True
        should_convert_mp3 = False
    
    if(mask == "AUDIO"):
        should_download_video = False
        should_download_audio = True
        should_convert_mp3 = False

    if(mask == "VIDEO"):
        should_download_video = True
        should_download_audio = False
        should_convert_mp3 = False
    return (should_download_video, should_download_audio, should_convert_mp3)

def handle_download(url, mask):
    starting_time = time.perf_counter()
    download(url, mask)
    ending_time = time.perf_counter()
    delta = ending_time - starting_time
    output = delta / 60 if delta >= 60 else delta
    unit_label = "minutes" if delta >= 60 else "seconds"
    logger.info(f"Request completed in {output:.2f} {unit_label}")
    return url