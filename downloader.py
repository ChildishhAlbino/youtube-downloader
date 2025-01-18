from pytubefix import Stream, YouTube, Playlist
from ffmpy import FFmpeg
from os.path import exists
from os import makedirs, remove, environ
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import time
import logging
import uuid
import shutil


def get_base_path():
    return str(environ.get("YT_DOWNLOADER_PATH"))

MAX_PROCESS_WORKERS_KEY="MAX_PROCESS_WORKERS"
base_path = get_base_path()
max_process_workers = int(environ.get(MAX_PROCESS_WORKERS_KEY)) if MAX_PROCESS_WORKERS_KEY in environ else 4

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def remove_relative_path_prefix(relative_path):
    value = relative_path
    if("./" in relative_path[0:2]):
        value = relative_path[2:]
    logger.debug(f"derelative={value}")
    return value

def replace_illegal_chars(starting, illegal_chars=["|"]):
    current_value = starting
    for char in illegal_chars:
        current_value = current_value.replace(char, "")
    return current_value

def get_folder_path(folder_name) -> str:
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

def download_playlist(download_id, url, options):
    (_, _, should_convert_mp3) = options
    playlist = Playlist(url)
    logger.info(playlist.title)
    folder_name = replace_illegal_chars(playlist.title)
    temporary_download_folder = get_temporary_download_folder(download_id=download_id)
    folder_path = f"{temporary_download_folder}/{get_path_section_if_exists(folder_name)}"
    make_folder_if_not_exists(folder_path)
    logger.debug(playlist)
    logger.debug(f"Playlist length: {len(playlist.video_urls)}")
    with ThreadPoolExecutor() as t:
        mapped = t.map(get_video_from_url, playlist.video_urls)
        mapped = [(download_id, item, folder_name, options) for item in mapped]
    with ProcessPoolExecutor(max_workers=max_process_workers) as t:
        mapped = t.map(download_video_direct, mapped)
        mapped = [item for item in mapped]
    logger.info(f"Results: {mapped}")
    if should_convert_mp3:
        with ThreadPoolExecutor() as t:
            mapped = t.map(convert_to_mp3, mapped)

def on_progress(stream, chunk: bytes, bytes_remaining: int):
    filesize = stream.filesize
    bytes_received = filesize - bytes_remaining
    percentage = (bytes_received / filesize) * 100
    logger.info(f"Downloading {stream.type} steam for \"{stream.title}\"={percentage:.2f}%")

def get_video_from_url(url):
    try:
        # TODO: Fix bug with client...
        video = YouTube(url, client="MWEB", use_oauth=True, allow_oauth_cache=True, on_progress_callback=on_progress)
        return video
    except Exception as ex:
        logger.error(f"Error while fetching Youtube video for url {url}. Details: {ex}")
        return None

BASE_RETRY_DELAY = 10
def download_with_delayed_retry(source_title, stream, destination_folder_path, prefix) -> str:
    res = None
    fib1 = 0
    fib2 = 1
    while(res is None):
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
                logger.warning(f"Sleep time ({sleep_duration} seconds) is getting very long. Please check errors and kill the job.")
            if(fib2 > 100):
                raise Exception(f"'{source_title}' :: was retrying for way too long. Fix ya shtuff...")
    logger.debug(f"'{source_title}' :: {stream.type} is Completed.")
    return res

def get_captions_with_delayed_retry(video):
    res = None
    fib1 = 0
    fib2 = 1
    while(res is None):
        try:    
            res = video.captions
        except Exception as ex:
            sleep_duration = BASE_RETRY_DELAY * fib2
            logger.error(f"Error when downloading stream for '{video.title}' :: retrying in {sleep_duration} seconds :: Details: {ex}")
            time.sleep(sleep_duration)
            temp = fib2
            fib2 = fib2 + fib1
            fib1 = temp
            logger.debug(f"fib1 = {fib1} | fib2 = {fib2}")
            if(fib2 > 30):
                logger.warn(f"Sleep time ({sleep_duration} seconds) is getting very long. Please check errors and kill the job.")
            if(fib2 > 100):
                raise Exception(f"'{video.title}' :: was retrying for way too long. Fix ya shtuff...")
    logger.debug(f"'{video.title}' :: Getting Captions is Completed.")
    return res

def download_video_direct(args):
    (download_id, video, folder_name, options) = args
    (should_download_video, should_download_audio, convert_to_mp3) = options
    optional_path_section = get_path_section_if_exists(folder_name)
    temporary_download_folder = get_temporary_download_folder(download_id=download_id)
    temporary_folder_section = f"{temporary_download_folder}{optional_path_section}"
    temporary_folder_path=get_folder_path(temporary_folder_section)
    destination_folder_path=temporary_folder_path.replace(temporary_folder_section, optional_path_section)
    logger.debug(f"temp={temporary_folder_path} :: output={destination_folder_path}")
    try:
        logger.info("Downloading Video: %s" % video.title)
        highest_quality_video_stream = get_highest_quality_video_stream(video)
        logger.debug("Highest Quality Video Stream: " + str(highest_quality_video_stream))
        highest_quality_audio_stream = get_highest_quality_audio_stream(video)
        logger.debug("Highest Quality Audio Stream: " + str(highest_quality_audio_stream))
        video_res = download_with_delayed_retry(video.title, highest_quality_video_stream, temporary_folder_path, "__VIDEO__") if (should_download_video) else None
        audio_res = download_with_delayed_retry(video.title, highest_quality_audio_stream, temporary_folder_path, "__AUDIO__") if (should_download_audio) else None

        video_captions = get_captions_with_delayed_retry(video)
        language_keys = [key.code for key in list(video_captions.keys()) if "en" in key.code and "a." not in key.code]
        logger.debug(f"all_captions={language_keys}")       
        english_captions = video.captions.get(language_keys[0]) if len(language_keys) > 0 else None
        logger.debug(f"english_captions={english_captions}")

        logger.info(f"{video.title} | Streams downloaded! Don't accidentally cross them!!")

        subtitle_file_path=None
        if(english_captions is not None):
            try:
                srt_captions = english_captions.generate_srt_captions()
                subtitle_file_path = video_res.replace("__VIDEO__", "__SUBTITLES__").replace(".mp4", ".srt")
                logger.info(subtitle_file_path)
                with open(subtitle_file_path, "w") as f:
                    f.write(srt_captions)
            except Exception as ex:
                logger.info("Generating subtitles did a bad...")
                logger.info(str(ex))
        temporary_folder_path_section = remove_relative_path_prefix(temporary_folder_path)
        if(video_res and audio_res):
            output_path = video_res.replace("__VIDEO__", "").replace(temporary_folder_path_section, destination_folder_path).replace(".webm", ".mp4")
            # multiline strings don't work in logs
            logger.debug(f"temp={temporary_folder_path_section}")
            logger.debug(f"dest={destination_folder_path}")
            logger.debug(f"output={output_path}")
            
            make_folder_if_not_exists(folder_name)
            merge_audio_and_video(video_res, audio_res, subtitle_file_path, output_path)
            logger.info(f"{video.title} has been merged together.")
            return output_path
        elif(audio_res):
            output_path = audio_res.replace("__AUDIO__", "").replace(temporary_folder_path_section, destination_folder_path)
            shutil.copy2(audio_res, output_path)
            return audio_res
        else:
            output_path = video_res.replace("__VIDEO__", "").replace(temporary_folder_path_section, destination_folder_path)
            shutil.copy2(video_res, output_path)
            return video_res
    except Exception as ex:
        logger.error(f"{type(ex)}")
        logger.error(f"Error when downloading video: \"{video.title}\"... Details: {ex}")
        return None

def download_video(download_id, url, options):
    (should_download_video, should_download_audio, should_convert_mp3) = options
    logger.info(f"{should_download_audio} {should_convert_mp3}")
    video = get_video_from_url(url)
    res = download_video_direct((download_id, video, None, options))
    if res is None:
        raise Exception("AHHH")
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

def convert_to_mp3(filePath):
    logger.info("Converting %s" % filePath)
    cmd = FFmpeg(
        global_options="-loglevel quiet -y -vn -ar 44100 -ac 2 -q:a 0",
        inputs={filePath: None},
        outputs={filePath.replace(".mp4", ".mp3").replace(".webm", ".mp3"): None}
    )
    cmd.run()
    return cmd.cmd

def merge_audio_and_video(video_path, audio_path, subtitle_path, output_path):
    logger.debug("Crossing the streams...")
    logger.debug("Creating merged file: %s" % output_path)
    inputs = {video_path: None, audio_path: None}
    if(subtitle_path is not None):
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
        logger.error(f"Error when crossing streams. Details {ex}")
        raise ex

def get_temporary_download_folder(download_id):
    return f".tmp/{download_id}"

def download(url, content_mask):
    download_id = str(uuid.uuid4())
    temporary_download_folder = get_temporary_download_folder(download_id=download_id)
    make_folder_if_not_exists(temporary_download_folder)
    options = get_options_from_mask(content_mask)
    if "/playlist?list=" in url:
        download_playlist(download_id, url, options)
    elif "/watch?v=" in url:
        download_video(download_id, url, options)
    else:
        logger.info("Please provide a valid Youtube Link.")
    logger.info("Download finished. Waiting 10 seconds to do cleanup...")
    time.sleep(10)
    shutil.rmtree(get_folder_path(temporary_download_folder))

def get_options_from_mask(mask):
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
    if url == None:
        raise Exception("URL IS NULL!");
    try:
        starting_time = time.perf_counter()
        download(url, mask)
        ending_time = time.perf_counter()
        delta = ending_time - starting_time
        output = delta / 60 if delta >= 60 else delta
        unit_label = "minutes" if delta >= 60 else "seconds"
        logger.info(f"Request completed in {output:.2f} {unit_label}")
        return url
    except Exception as ex:
        logger.error(ex)


if __name__ == "__main__":
    print("Starting from the main dunder...")
    url = None
    mask = "ALL"
    # transformer cybertron ep 1
    # url = "https://www.youtube.com/watch?v=G0UjB-ywdo4&t=365s"

    # beyblade og ep 1
    # url = "https://www.youtube.com/watch?v=MZX00vlN1ps"

    # dmg 2024 guide
    # url = "https://www.youtube.com/watch?v=xWNT9N3cE2U&t=2039s"

    # cr c1 ep 1
    # url = "https://www.youtube.com/watch?v=i-p9lWIhcLQ&t=28s"

    # frieza says hello monkeys
    url = "https://www.youtube.com/watch?v=CNRJD2cDpiE"

    mask = "AUDIO"
    # mask = "VIDEO"

    handle_download(url, mask)
