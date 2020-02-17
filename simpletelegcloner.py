# encoding = utf-8
import io
import logging
import os.path
import re
import shutil
import subprocess
import sys
import threading
import time
from telegram.ext import Updater
from telegram.ext import MessageHandler, CommandHandler, Filters

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf8')


# config

path_to_gclone = ''  # Optional
path_to_gclone_config = ''  # Optional

# telegram bot token refer to https://core.telegram.org/bots#3-how-do-i-create-a-bot
# e.g. '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'
token = ''

# First ID will be master ID so set it to your own id. Use /id to check your id e.g. [123456]
# If you don't set it, the bot won't do anything except responding to /id.
message_from_user_white_list = []

destination_folder = ""  # Destination Google drive folder ID e.g. "abcedfghijklmn"
destination_folder_name = "My Drive"  # Name of gdrive folder, e.g. "My Drive"

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
console_logger = logging.StreamHandler()
console_logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_logger.setFormatter(formatter)
root_logger.addHandler(console_logger)

this_file_name = os.path.basename(os.path.splitext(os.path.basename(__file__))[0])
file_logger = logging.FileHandler(this_file_name + '.log', 'a', 'utf-8')
file_logger.setLevel(logging.INFO)
file_logger.setFormatter(formatter)
root_logger.addHandler(file_logger)

if path_to_gclone and not os.path.isfile(path_to_gclone):
    path_to_gclone = shutil.which(path_to_gclone)
    if not os.path.isfile(path_to_gclone):
        logging.warning('gclone executable is not found.')
        input("Press Enter to continue...")
        sys.exit(0)
logging.debug('Found gclone: ' + path_to_gclone)

if not os.path.isfile(path_to_gclone_config):
    path_to_gclone_config = None
    logging.debug('Cannot find gclone config. Use system gclone config instead.')
else:
    logging.debug('Found gclone config: ' + path_to_gclone_config)

FNULL = open(os.devnull, 'w')


class FolderIDList:
    def __init__(self, name, _id):
        self.name = name  
        self.id = _id


def get_id(update, context):
    if len(message_from_user_white_list) and (update.message.chat.id not in message_from_user_white_list):
        return
    update.message.reply_text(update.message.chat.id)
    logging.info('telegram user {0} has requested its id.'.format(update.message.chat.id))


def process_message(update, context):
    if not update.message:
        return
    if update.message.chat.id not in message_from_user_white_list:
        logging.debug('Ignore message from {0}.'.format(update.message.chat.id))
        return
    logging.debug(update.message)
    if update.message.photo:
        text = update.message.caption
        entities = update.message.caption_entities
        logging.debug('This message contains photo.')
    else:
        text = update.message.text
        entities = update.message.entities
    
    folder_ids = []
    k = 0
    for entity in entities:
        offset = entity.offset
        length = entity.length
        if entity.type == 'text_link':
            url = entity.url
            name = text[offset:offset + length].strip('/')
        elif entity.type == 'url':
            url = text[offset:offset + length]
            name = 'file{:03d}'.format(k)
        else:
            continue

        logging.debug('Found {0}: {1}.'.format(name, url))
        folder_id = parse_folder_id_from_url(url)
        if not folder_id:
            continue

        folder_ids.append(FolderIDList(name, folder_id))
        logging.info('Found {0} with folder_id {1}.'.format(name, folder_id))

    if len(folder_ids) == 0:
        logging.debug('Cannot find any legit folder id.')
        return
    title = text.split('\n', 1)[0]
    t = threading.Thread(target=fire_save_files, args=(context, folder_ids, title))
    t.start()


def parse_folder_id_from_url(url):
    folder_id = None
    
    pattern = r'https://drive\.google\.com/drive/folders/([\w.\-_]+)(\?[\=\w]+)?' \
              r'|https\:\/\/drive\.google\.com\/folderview\?id=([\w.\-_]+)(\&[=\w]+)?' \
              r'|https\:\/\/drive\.google\.com\/open\?id=([\w.\-_]+)(\&[=\w]+)?' \
              r'|https\:\/\/drive\.google\.com\/a\/[\w.\-_]+\/file\/d\/([\w\.\-_]+)\/view' \
              r'|https\:\/\/drive\.google\.com\/uc\?id\=([\w.\-_]+)&? '
    
    x = re.search(pattern, url)
    if x:
        folder_id = ''.join(filter(None, x.groups()))

    logging.debug('folder_id: ' + str(folder_id))
    return folder_id
    

def fire_save_files(context, folder_ids, title):
    is_multiple_ids = len(folder_ids) > 1 
    message = "[" + title + "] has been saved to [" + destination_folder_name + "]."

    for folder_id in folder_ids:
        if is_multiple_ids:
            destination_path = title + '/' + folder_id.name
            message += '\n' + destination_path
        else:
            destination_path = title
        command_line = [
            path_to_gclone,
            'copy',
            '--drive-server-side-across-configs',
            '-v',
            '--transfers',
            '6',
            '--tpslimit',
            '6',
            '--ignore-existing'
        ]
        if path_to_gclone_config:
            command_line += ['--config',path_to_gclone_config]
        command_line += [
            "--log-file={0}-{1}.log".format(this_file_name, time.strftime("%Y%m%d")),
            "gc:{"+folder_id.id+"}",
            ("gc:{"+destination_folder+"}/" + destination_path).encode('utf-8')
        ]
        
        logging.debug('command line: ' + str(command_line))
        subprocess.call(command_line,  stdout=FNULL, stderr=subprocess.STDOUT, encoding="utf-8", shell=True)
        
    context.bot.send_message(chat_id=message_from_user_white_list[0], text=message)
    logging.info(message)


updater = Updater(token=token, use_context=True)
updater.dispatcher.add_handler(CommandHandler('id', get_id))
updater.dispatcher.add_handler(MessageHandler(Filters.text | Filters.photo, process_message))
updater.start_polling()
updater.idle()

