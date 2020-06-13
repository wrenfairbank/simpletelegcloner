#!/usr/bin/python3
# -*- coding: utf-8 -*-
import datetime
import logging
import os.path
import re
import shutil
import subprocess
import sys
import threading

from telegram import ParseMode
from telegram.ext import MessageHandler, CommandHandler, Filters
from telegram.ext import Updater

# config

path_to_gclone = ''  # Optional
path_to_gclone_config = ''  # Optional. Point it to the gclone .conf file.
gclone_remote_name = 'gc'  # Default value is gc. Change it to what you have got in your gclone config.

# telegram bot token refer to https://core.telegram.org/bots#3-how-do-i-create-a-bot
# e.g. '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'
token = ''

# First ID will be master ID so set it to your own id. Use /id to check your id e.g. [123456]
# If you don't set it, the bot won't do anything except responding to /id.
message_from_user_white_list = []

destination_folder = ""  # Destination Google drive folder ID e.g. "abcedfghijklmn"
destination_folder_name = ""  # Name of gdrive folder, e.g. "My Drive"

logger = logging.getLogger(__name__)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
console_logger = logging.StreamHandler()
console_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_logger.setFormatter(formatter)
root_logger.addHandler(console_logger)

this_file_name = os.path.basename(os.path.splitext(os.path.basename(__file__))[0])
file_logger = logging.handlers.TimedRotatingFileHandler('./logs/' + this_file_name, encoding='utf-8', when='midnight')
file_logger.suffix = "%Y-%m-%d.log"
file_logger.extMatch = re.compile(r"^\d{4}-\d{2}-\d{2}\.log$")
file_logger.setLevel(logging.DEBUG)
file_logger.setFormatter(formatter)
root_logger.addHandler(file_logger)

logging.getLogger('googleapiclient').setLevel(logging.CRITICAL)
logging.getLogger('googleapiclient.discover').setLevel(logging.CRITICAL)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.CRITICAL)
logging.getLogger('google.auth.transport.requests').setLevel(logging.INFO)

logging.getLogger('telegram.bot').setLevel(logging.INFO)
logging.getLogger('telegram.ext.dispatcher').setLevel(logging.INFO)
logging.getLogger('telegram.vendor.ptb_urllib3.urllib3.connectionpool').setLevel(logging.INFO)

if not os.path.isfile(path_to_gclone):
    path_to_gclone = shutil.which('gclone')
    if not path_to_gclone:
        logger.warning('gclone executable is not found.')
        input("Press Enter to continue...")
        sys.exit(0)
logger.info('Found gclone: ' + path_to_gclone)

if not gclone_remote_name:
    logger.warning('gclone remote name is not found.')
    input("Press Enter to continue...")
    sys.exit(0)

if not os.path.isfile(path_to_gclone_config):
    path_to_gclone_config = None
    logger.debug('Cannot find gclone config. Use system gclone config instead.')
else:
    logger.info('Found gclone config: ' + path_to_gclone_config)

if not destination_folder:
    logger.warning('Destination folder id is not provided.')
    input("Press Enter to continue...")
    sys.exit(0)
logger.info('Found destination_folder: ' + destination_folder)

if not token:
    logger.warning('telegram token is not provided.')
    input("Press Enter to continue...")
    sys.exit(0)
logger.info('Found token: ' + token)


def get_id(update, context):
    if len(message_from_user_white_list) and (update.message.chat.id not in message_from_user_white_list):
        return
    update.message.reply_text(update.message.chat.id)
    logger.info('telegram user {0} has requested its id.'.format(update.message.chat.id))


def process_message(update, context):
    if not update.message:
        return
    if update.message.caption:
        text = update.message.caption
        entities = update.message.parse_caption_entities()
        logger.debug('This message contains caption.')
    else:
        text = update.message.text
        entities = update.message.parse_entities()

    folder_ids = {}
    k = 0
    for entity in entities:
        offset = entity.offset
        length = entity.length
        if entity.type == 'text_link':
            url = entity.url
            name = text[offset:offset + length].strip('/').strip()
        elif entity.type == 'url':
            url = text[offset:offset + length]
            name = 'file{:03d}'.format(k)
        else:
            continue

        logger.debug('Found {0}: {1}.'.format(name, url))
        folder_id = parse_folder_id_from_url(url)
        if not folder_id:
            continue

        folder_ids[folder_id] = name
        logger.info('Found {0} with folder_id {1}.'.format(name, folder_id))

    if len(folder_ids) == 0:
        logger.debug('Cannot find any legit folder id.')
        return
    if '\n' in text:
        title = text.split('\n', 1)[0].strip('/').strip()
    else:
        title = datetime.datetime.now().strftime("%Y%m%d")
    logger.info('Saving {0} to folder [{1}]'.format(title, destination_folder_name))
    t = threading.Thread(target=fire_save_files, args=(context, folder_ids, title))
    t.start()


def parse_folder_id_from_url(url):
    folder_id = None

    pattern = r'https://drive\.google\.com/drive/(?:u/[\d]+/)?folders/([\w.\-_]+)(?:\?[\=\w]+)?' \
              r'|https\:\/\/drive\.google\.com\/folderview\?id=([\w.\-_]+)(?:\&[=\w]+)?' \
              r'|https\:\/\/drive\.google\.com\/open\?id=([\w.\-_]+)(?:\&[=\w]+)?' \
              r'|https\:\/\/drive\.google\.com\/(?:a\/[\w.\-_]+\/)?file\/d\/([\w\.\-_]+)\/' \
              r'|https\:\/\/drive\.google\.com\/(?:a\/[\w.\-_]+\/)?uc\?id\=([\w.\-_]+)&?'

    x = re.search(pattern, url)
    if x:
        folder_id = ''.join(filter(None, x.groups()))

    logger.debug('folder_id: ' + str(folder_id))
    return folder_id


def fire_save_files(context, folder_ids, title):
    is_multiple_ids = len(folder_ids) > 1
    message = 'Saving [{0}] to [{1}].\n\n'.format(title, destination_folder_name)
    logger.debug(message)
    rsp = context.bot.send_message(chat_id=message_from_user_white_list[0], text=message, parse_mode=ParseMode.HTML)
    message_id = rsp.message_id

    for folder_id in folder_ids:
        if is_multiple_ids:
            destination_path = title + '/' + folder_ids[folder_id]
        else:
            destination_path = title
        command_line = [
            path_to_gclone,
            'copy',
            '--drive-server-side-across-configs',
            '-P',
            '--stats',
            '1s',
            '--transfers',
            '6',
            '--tpslimit',
            '6',
            '--ignore-existing',
            '--include',
            '*.{mp4,mkv,flac,iso,nfo,srt,ass,sup,ssa,avi,ts,dsf,m2ts}'
        ]
        if path_to_gclone_config:
            command_line += ['--config', path_to_gclone_config]
        command_line += [
            # "--log-file={0}-{1}.log".format('gclone', time.strftime("%Y%m%d")),
            'gc:{' + folder_id + '}',
            ('gc:{' + destination_folder + '}/' + destination_path)
        ]

        logger.debug('command line: ' + str(command_line))

        process = subprocess.Popen(command_line, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8',
                                   universal_newlines=True)
        progress_checked_files = 0
        progress_total_check_files = 0
        progress_transferred_file = 0
        progress_total_files = 0
        progress_file_percentage = 0
        progress_file_percentage_10 = 0
        progress_transferred_size = '0'
        progress_total_size = '0 Bytes'
        progress_speed = '-'
        progress_eta = '-'
        progress_size_percentage_10 = 0
        regex_checked_files = r'Checks:\s+(\d+)\s+/\s+(\d+)'
        regex_total_files = r'Transferred:\s+(\d+) / (\d+), (\d+)%'
        regex_total_size = r'Transferred:[\s]+([\d.]+\s*[kMGTP]?) / ([\d.]+[\s]?[kMGTP]?Bytes),' \
                           r'\s*(?:\-|(\d+)\%),\s*([\d.]+\s*[kMGTP]?Bytes/s),\s*ETA\s*([\-0-9hmsdwy]+)'
        message_progress_last = ''
        progress_update_time = datetime.datetime.now() - datetime.timedelta(minutes=5)
        while True:
            try:
                output = process.stdout.readline()
            except:
                continue
            if output == '' and process.poll() is not None:
                break
            if output:
                match_total_files = re.search(regex_total_files, output)
                if match_total_files:
                    progress_transferred_file = int(match_total_files.group(1))
                    progress_total_files = int(match_total_files.group(2))
                    progress_file_percentage = int(match_total_files.group(3))
                    progress_file_percentage_10 = progress_file_percentage // 10
                match_total_size = re.search(regex_total_size, output)
                if match_total_size:
                    progress_transferred_size = match_total_size.group(1)
                    progress_total_size = match_total_size.group(2)
                    progress_size_percentage = int(match_total_size.group(3)) if match_total_size.group(3) else 0
                    progress_size_percentage_10 = progress_size_percentage // 10
                    progress_speed = match_total_size.group(4)
                    progress_eta = match_total_size.group(5)
                match_checked_files = re.search(regex_checked_files, output)
                if match_checked_files:
                    progress_checked_files = int(match_checked_files.group(1))
                    progress_total_check_files = int(match_checked_files.group(2))
                progress_max_percentage_10 = max(progress_size_percentage_10, progress_file_percentage_10)
                message_progress = '<a href="https://drive.google.com/open?id={}">{}</a>\n' \
                                   '检查文件：<code>{} / {}</code>\n' \
                                   '文件数量：<code>{} / {}</code>\n' \
                                   '任务容量：<code>{} / {}</code>\n' \
                                   '传输速度：<code>{} ETA {}</code>\n' \
                                   '任务进度：<code>[{}] {: >4}%</code>'.format(
                    folder_id,
                    destination_path,
                    progress_checked_files,
                    progress_total_check_files,
                    progress_transferred_file,
                    progress_total_files,
                    progress_transferred_size,
                    progress_total_size,
                    progress_speed,
                    progress_eta,
                    '█' * progress_file_percentage_10 + '░' * (
                            progress_max_percentage_10 - progress_file_percentage_10) + ' ' * (
                            10 - progress_max_percentage_10),
                    progress_file_percentage)
                if message_progress != message_progress_last:
                    if datetime.datetime.now() - progress_update_time > datetime.timedelta(seconds=5):
                        temp_message = '{}\n\n{}'.format(message, message_progress)
                        context.bot.edit_message_text(chat_id=message_from_user_white_list[0], message_id=message_id,
                                                      text=temp_message, parse_mode=ParseMode.HTML)
                        message_progress_last = message_progress
                        progress_update_time = datetime.datetime.now()
        rc = process.poll()
        message_progress_heading, message_progress_content = message_progress.split('\n', 1)
        if progress_file_percentage == 0 and progress_checked_files > 0:
            message = '{}{}✅\n已存在\n\n'.format(message, message_progress_heading)
        else:
            message = '{}{}{}\n{}\n\n'.format(message,
                                              message_progress_heading,
                                              '✅' if rc == 0 else '❌',
                                              message_progress_content
                                              )
        context.bot.edit_message_text(chat_id=message_from_user_white_list[0], message_id=message_id, text=message,
                                      parse_mode=ParseMode.HTML)

    message_append = 'Finished.'
    message += message_append
    logger.debug(message)
    context.bot.edit_message_text(chat_id=message_from_user_white_list[0], message_id=message_id, text=message,
                                  parse_mode=ParseMode.HTML)


updater = Updater(token=token, use_context=True)
updater.dispatcher.add_handler(CommandHandler('id', get_id))
updater.dispatcher.add_handler(
    MessageHandler(Filters.chat(message_from_user_white_list) & (Filters.text | Filters.caption), process_message))
updater.start_polling()
updater.idle()
