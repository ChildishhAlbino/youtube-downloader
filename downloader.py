from pytubefix import YouTube, Playlist
from ffmpy import FFmpeg
from os.path import exists
from os import makedirs, remove, environ
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import time
import logging
import uuid
import shutil

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

def make_folder_if_not_exists(folder_name):
    path = get_folder_path(folder_name)
    logger.debug(f"Checking if path={path} exists...")
    if not exists(path):
        logger.debug("MAKING DIRECTORY " + str(path))
        makedirs(path)


def get_path_section_if_exists(section):
    if(section):
        return f"/{section}"
    else:
        return ""

def download_playlist(job_id, url, options):
    (_, __, should_convert_mp3) = options
    playlist = Playlist(url)
    logger.info(playlist.title)
    folder_name = replace_illegal_chars(playlist.title)
    folder_path = f".tmp/{job_id}/{get_path_section_if_exists(folder_name)}"
    make_folder_if_not_exists(folder_path)
    logger.debug(playlist)
    logger.debug(f"Playlist length: {len(playlist.video_urls)}")
    with ThreadPoolExecutor() as t:
        mapped = t.map(get_video_from_url, playlist.video_urls)
        mapped = [(job_id, item, folder_name, options) for item in mapped]
    with ProcessPoolExecutor(max_workers=max_process_workers) as t:
        mapped = t.map(download_video_direct, mapped)
        mapped = [item for item in mapped]
    logger.info(f"Results: {mapped}")
    if should_convert_mp3:
        with ThreadPoolExecutor() as t:
            mapped = t.map(convert_to_mp3, mapped)
    time.sleep(10)
    shutil.rmtree(get_folder_path(f".tmp/{job_id}"))

def on_progress(stream, chunk: bytes, bytes_remaining: int):
    filesize = stream.filesize
    bytes_received = filesize - bytes_remaining
    percentage = (bytes_received / filesize) * 100
    logger.info(f"Downloading {stream.title}={percentage:.2f}%")

def get_video_from_url(url):
    try:
        video = YouTube(url, use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        return video
    except Exception as ex:
        logger.error(f"Error while fetching Youtube video for url {url}. Details: {ex}")
        return None

BASE_RETRY_DELAY = 10
def download_with_delayed_retry(source_title, stream, destination_folder_path, prefix):
    res = None
    fib1 = 0
    fib2 = 1
    while(res == None):
        try:    
            res = stream.download(skip_existing=True, output_path=destination_folder_path, filename_prefix=prefix, max_retries=10)
        except Exception as ex:
            sleep_duration = BASE_RETRY_DELAY * fib2
            logger.error(f"Error when downloading stream for '{source_title}' :: retrying in {sleep_duration} seconds :: Details: {ex}")
            time.sleep(sleep_duration)
            temp = fib2
            fib2 = fib2 + fib1
            fib1 = temp
            logger.debug(f"fib1 = {fib1} | fib2 = {fib2}")
            if(fib2 > 30):
                logger.warn(f"Sleep time ({sleep_duration} seconds) is getting very long. Please check errors and kill the job.")
            if(fib2 > 100):
                raise Exception(f"'{source_title}' :: was retrying for way too long. Fix ya shtuff...")
    logger.debug(f"'{source_title}' :: {stream.type} is Completed.")
    return res

def download_video_direct(args):
    (job_id, video, folder_name, options) = args
    (should_download_video, should_download_audio, _) = options
    optional_path_section = get_path_section_if_exists(folder_name)
    temporary_folder_path=get_folder_path(f".tmp/{job_id}{optional_path_section}")
    destination_folder_path=temporary_folder_path.replace(f".tmp/{job_id}{optional_path_section}", f"{optional_path_section}")
    logger.debug(f"temp={temporary_folder_path} :: output={destination_folder_path}")
    try:
        language_keys = [key.code for key in list(video.captions.keys()) if "en" in key.code and "a." not in key.code]
        logger.debug(f"all_captions={language_keys}")       
        english_captions = video.captions.get(language_keys[0]) if len(language_keys) > 0 else None
        logger.debug(f"english_captions={english_captions}")
        logger.info("Downloading Video: %s" % video.title)
        highest_quality_video_stream = get_highest_quality_video_stream(video)
        logger.debug("Highest Quality Video Stream: " + str(highest_quality_video_stream))
        highest_quality_audio_stream = get_highest_quality_audio_stream(video)
        logger.debug("Highest Quality Audio Stream: " + str(highest_quality_audio_stream))
        video_res = download_with_delayed_retry(video.title, highest_quality_video_stream, temporary_folder_path, "__VIDEO__") if (should_download_video) else None
        audio_res = download_with_delayed_retry(video.title, highest_quality_audio_stream, temporary_folder_path, "__AUDIO__") if (should_download_audio) else None
    
        logger.info(f"{video.title} | Streams downloaded! Don't accidentally cross them!!")

        subtitle_file_path=None
        if(english_captions != None):
            try:
                srt_captions = english_captions.generate_srt_captions()
                subtitle_file_path = video_res.replace("__VIDEO__", "__SUBTITLES__").replace(".mp4", ".srt")
                logger.info(subtitle_file_path)
                with open(subtitle_file_path, "w") as f:
                    f.write(srt_captions)
            except Exception as ex:
                logger.info("Generating subtitles did a bad...")
                logger.info(str(ex))
        if(video_res and audio_res):
            output_path = video_res.replace("__VIDEO__", "").replace(temporary_folder_path, destination_folder_path)
            make_folder_if_not_exists(folder_name)
            merge_audio_and_video(video_res, audio_res, subtitle_file_path, output_path)
            return output_path
        elif(audio_res):
            output_path = audio_res.replace("__AUDIO__", "").replace(temporary_folder_path, destination_folder_path)
            shutil.copy2(audio_res, output_path)
            return audio_res
        else:
            output_path = video_res.replace("__VIDEO__", "").replace(temporary_folder_path, destination_folder_path)
            shutil.copy2(video_res, output_path)
            return video_res
    except Exception as ex:
        logger.error(f"Error when downloading video: {video.title}... Details: {ex}")
        return None

def download_video(job_id, url, options):
    (should_download_video, should_download_audio, should_convert_mp3) = options
    video = get_video_from_url(url)
    res = download_video_direct((job_id, video, None, options))
    if(should_convert_mp3):
        convert_to_mp3(res)
        if(not should_download_video and should_download_audio):
            remove(res)
    time.sleep(10)
    shutil.rmtree(get_folder_path(f".tmp/{job_id}"))

def get_highest_quality_video_stream(video):
    relevant_streams = video.streams.filter(
        only_video=True, progressive=False)
    return relevant_streams.first()

def get_highest_quality_audio_stream(video):
    webm_stream = video.streams.get_audio_only("webm")
    return webm_stream if webm_stream else video.streams.get_audio_only()

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
    logger.debug("Crossing the streams...")
    logger.debug("Creating merged file: %s" % output_path)
    inputs = {video_path: None, audio_path: None}
    if(subtitle_path != None):
        inputs[subtitle_path] = None

    global_options = "-loglevel quiet -y"

    if "FFMPEG_GLOBAL_FLAGS" in environ:
        flags = environ["FFMPEG_GLOBAL_FLAGS"]
        global_options = global_options + f" {flags}"

    logger.debug(global_options)
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
        raise ex

def download(url, content_mask):
    job_id = str(uuid.uuid4())
    make_folder_if_not_exists(f".tmp/{job_id}")
    options = set_options(content_mask)
    if "/playlist?list=" in url:
        download_playlist(job_id, url, options)
    elif "/watch?v=" in url:
        download_video(job_id, url, options)
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
