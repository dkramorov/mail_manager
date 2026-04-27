import datetime
import email
import json
import os
import smtplib
import subprocess
import time
import traceback

import imaplib
import smtplib

from email.header import decode_header, Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from managers.simple_logger import logger


class MockSettings:
    FULL_SETTINGS_SET = os.environ


try:
    from django.conf import settings
    hasattr(settings, 'DEBUG')
except Exception as e:
    logger.info('Exception from django.conf import settings: %s' % e)
    settings = MockSettings()


#import socket
#socket.setdefaulttimeout(10)


class MailProvider:

    def __init__(self,
                 login: str = None,
                 passwd: str = None,
                 imap_host: str = None,
                 imap_port: str = None,
                 smtp_host: str = None,
                 smtp_port: str = None):
        all_settings = settings.FULL_SETTINGS_SET
        self.login = all_settings.get('MAIL_LOGIN')
        if login:
            self.login = login
        self.passwd = all_settings.get('MAIL_PASSWD')
        if passwd:
            self.passwd = passwd
        self.imap_host = all_settings.get('MAIL_IMAP_HOST')
        if imap_host:
            self.imap_host = imap_host
        self.imap_port = all_settings.get('MAIL_IMAP_PORT')
        if imap_port:
            self.imap_port = imap_port
        self.smtp_host = all_settings.get('MAIL_SMTP_HOST')
        if smtp_host:
            self.smtp_host = smtp_host
        self.smtp_port = all_settings.get('MAIL_SMPT_PORT')
        if smtp_port:
            self.smtp_port = smtp_port


class SmtpManager(MailProvider):
    """SMTP клиент для почты"""

    def send_email(self, subject: str, body: str, to: list):
        """Отправка письма
           :param subject: Заголовок письма
           :param body: Тело письма
           :param to: получатель письма
        """
        cc = []
        bcc = []
        msg = MIMEMultipart()
        msg.preamble = subject
        msg['Subject'] = subject
        msg['From'] = self.login
        msg['To'] = ', '.join(to)
        if len(cc):
            msg['Cc'] = ', '.join(cc)
        if len(bcc):
            msg['Bcc'] = ', '.join(bcc)

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP('%s:%s' % (self.smtp_host, self.smtp_port))
        server.starttls()
        server.ehlo()
        server.login(self.login, self.passwd)
        server.sendmail(self.login, to, msg.as_string())
        server.quit()


class ImapManager(MailProvider):
    """IMAP клиент для почты"""

    def __init__(self, timeout: int = 10):
        """Подключение к серверу
        """
        super().__init__()
        self.conn = None
        self.authorized = False
        self.timeout = timeout

        print('[IMAP]: connecting to %s, timeout %s' % (self.imap_host, self.timeout))
        self.conn = imaplib.IMAP4_SSL(host=self.imap_host, port=self.imap_port, timeout=self.timeout)
        print('[IMAP]:  connected')
        if self.auth() == 'OK':
            logger.info('[IMAP]: authorized')
            self.authorized = True

    def auth(self):
        """Авторизация"""
        result = self.conn.login(self.login, self.passwd)
        logger.info('[IMAP]: logged in %s' % result[0])
        return result[0]

    def get_folders(self):
        """Получение списка папок на сервере
        """
        result = []
        retcode, resp = self.conn.list()
        if retcode == 'OK':
            folders = [item.decode('utf-8') for item in resp]
            for folder in folders:
                folder = folder.split('"|"')[-1].strip()
                item = {'name': folder, 'count': 0}
                retcode, letters = self.select_folder(folder)
                if retcode == 'OK':
                    item['count'] = letters[0].decode('utf-8')

                ids_new_messages = self.search('(UNSEEN)')
                if ids_new_messages:
                    item['ids'] = ids_new_messages

                result.append(item)
        return result

    def select_folder(self, folder):
        """Выбирает папку на сервере
           :param folder: папка в зажопинском формате
        """
        try:
            logger.info('[IMAP]: select folder %s' % folder)
            result = self.conn.select(folder)
            return result
        except Exception as e:
            logger.error('[IMAP] exception: %s' % str(e))
            logger.error('[ERROR] when select_folder: ', traceback.format_exc())
            result = ('ERROR', [])
        return result

    def search(self, search_str: str = '(UNSEEN)'):
        """Получение списка ID писем через пробел
           :param search_str: поисковая строка 'ALL' / UNSEEN
        """
        retcode, result = self.conn.search(None, search_str)
        if retcode == 'OK':
            items = result[0].decode('utf-8').split(' ')
            return [int(item) for item in items if item]
        logger.info('[IMAP] retcode is %s, for searching letters' % str(retcode))
        return []

    def save_attached_file(self, subpart):
        """Сохранение прикрепленного файла к сообщению
           :param subpart: Прикрепленный файла
                           Если msg.is_multipart(): тогда обходим for subpart in msg.walk()
           надо дополнительно и его декодить
        """
        payload = subpart.get_payload(decode=True)
        filename = subpart.get_filename()
        if not filename:
            #logger.info('filename absent, passing...')
            return

        # get_filename() не пашет, когда UTF-8 символы есть пишет такую лабуду
        # ?utf-8?B?0JrQmiDRiNCw0LMgMSAueGxzeC5lbmM=?="; size=15192;
        filename, encoding = decode_header(filename)[0]
        if encoding:
            filename = filename.decode(encoding)

        fname = filename.split('/')[-1]
        save_path = os.path.join('/tmp', fname)
        if os.path.exists(save_path):
            logger.info('%s already exists' % save_path)
        else:
            with open(save_path, 'wb') as fp:
                fp.write(payload)
                fp.close()
        return fname

    def get_headers(self, part):
        """Получем заголовки по части письма
           :param part: полученная часть из письма через fetch (for part in data)
        """
        if not isinstance(part, (tuple, list)):
            return {}
        result = {}
        msg = email.message_from_string(part[1].decode('utf-8'))
        s = email.header.make_header(email.header.decode_header(str(msg['Subject'])))
        result['subject'] = str(s)
        t = email.header.make_header(email.header.decode_header(str(msg['To'])))
        result['to'] = str(t)
        f = email.header.make_header(email.header.decode_header(str(msg['From'])))
        result['from'] = str(f)

        date_tuple = email.utils.parsedate_tz(msg['Date'])
        if date_tuple:
            local_date = datetime.datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
            result['date'] = local_date.strftime('%d-%m-%Y')
            result['time'] = local_date.strftime('%H:%M:%S')

        if 'content_type' not in result:
            result['content_type'] = msg.get_content_type()
        return result

    def fetch_msg(self, data):
        """Получем файлы из письма
           :param data: полученное письмо через fetch
        """
        result = {'files': []}
        for part in data:
            if not isinstance(part, (tuple, list)):
                continue
            result.update(self.get_headers(part=part))
            msg = email.message_from_string(part[1].decode('utf-8'))
            if msg.is_multipart():
                for subpart in msg.walk():
                    if subpart.get_content_maintype == 'multipart':
                        continue
                    fname = self.save_attached_file(subpart=subpart)
                    if fname:
                        result['files'].append(fname)
                    # Получение тела
                    payload = subpart.get_payload(decode=True)
                    if payload:
                        try:
                            result['body'] = payload.decode('utf-8')
                            # Дополнительно декодим юникод
                            result['body'] = result['body'].encode().decode('unicode-escape')
                        except Exception as e:
                            pass
        return result

    def get_body(self, msg, result: dict):
        """Получем текст письма
           :param msg: полученное письмо через fetch,
                       затем message_from_string(part[1].decode('utf-8'))
           :param result: аккумуляция результата для multipart/mixed
        """
        if msg.is_multipart():
            for part in msg.get_payload():
                self.get_body(part, result)
        else:
            body = msg.get_payload(decode=True)
            # print(body)
            # body = body.decode('utf-8') if body else ''
            if 'content' not in result:
                result['content'] = b''
            result['content'] += body
        return result

    def get_ids_letters(self, folder: str, cond: str = None):
        """Получить идентификаторы писем в папке
           :param folder: папка с сообщениями
           :param cond: условие поиска '(SINCE "01-Jan-2012" BEFORE "02-Jan-2012")'
        """
        self.select_folder(folder)
        letters = self.search('(ALL)' if not cond else cond)
        letters = letters[::-1]
        return letters

    def create_time_cond(self, since: datetime.datetime = None, before: datetime.datetime = None):
        """Создать условие для получения писем '(SINCE "01-Jan-2012" BEFORE "02-Jan-2012")'
           :param since: с какой даты
           :param before: по какую дату
        """
        cond = []
        if since:
            cond.append('SINCE "%s"' % since.strftime('%d-%b-%Y'))
        if before:
            cond.append('BEFORE "%s"' % before.strftime('%d-%b-%Y'))
        return '(' + ' '.join(cond) + ')'


    def get_letters(self,
                    folder: str,
                    page: int = 0,
                    by: int = 3,
                    cond: str = None,
                    ids_for_pass: list = None,
                    from_emails: list = None):
        """Выбор всех сообщений
           :param folder: папка с сообщениями
           :param page: страница
           :param by: количество писем
           :param cond: условие поиска '(SINCE "01-Jan-2012" BEFORE "02-Jan-2012")'
           :param ids_for_pass: ид писем, которые пропускать (уже получали)
           :param from_emails: искать по отправителям email
        """
        if from_emails:
            from_emails = [from_email.lower() for from_email in from_emails]
        result = []
        letters = self.get_ids_letters(folder=folder, cond=cond)
        start = page * by
        end = page * by + by
        logger.info('total letters: %s, fetching %s - %s' % (len(letters), start, end))
        for letter in letters[start:end]:
            if isinstance(ids_for_pass, (list, tuple)):
                if letter in ids_for_pass:
                    #logger.info('get_letters: passing %s' % letter)
                    continue
            retcode, data = self.conn.fetch(str(letter), '(RFC822)')
            if not retcode == 'OK':
                continue

            if from_emails:
                # Ищем только по нужным отправителям
                # from бывает с контактом: Шпилер Татьяна <t.shpiler@fterra.ru>
                headers = {}
                for part in data:
                    headers.update(self.get_headers(part=part))
                passing = True
                for from_email in from_emails:
                    if from_email in headers.get('from', '').lower():
                        passing = False
                if passing:
                    #logger.info('passing from %s' % headers.get('from'))
                    continue

            result.append({
                'id': letter,
                'email': self.fetch_msg(data),
            })
        return result

    def get_enc_files(self, folder: str = 'INBOX', ids_for_pass: list = None, days_ago: int = 5):
        """Получаем с почты все файлы с зашифрованными реестрами
           :param folder: папка из которой получаем
           :param ids_for_pass: ид писем, которые пропускать (уже получали)
           :param days_ago: количество дней за которые получем
        """
        checked = []
        result = []
        by = 50
        passing_numbers = []
        now = datetime.datetime.now()
        long_ago = now - datetime.timedelta(days=days_ago)
        logger.info('Проверемя за последние %s дней' % days_ago)
        retcode, data = self.select_folder(folder=folder)
        if retcode == 'OK':
            cond = '(SINCE "%s")' % long_ago.strftime('%d-%b-%Y')
            ids = self.search(search_str=cond)
            count = len(ids)
            pages = int(count / by) + 1
            for i in range(pages):
                rows = ids[i * by:i * by + by]
                for letter in rows:
                    if isinstance(ids_for_pass, (list, tuple)):
                        if letter in ids_for_pass:
                            passing_numbers.append(letter)
                            continue

                    retcode, data = self.conn.fetch(str(letter), '(RFC822)')
                    if not retcode == 'OK':
                        print('not correct retcode=%s' % retcode)
                        continue
                    checked.append(letter)
                    result.append({
                        'id': letter,
                        'email': self.fetch_msg(data, letter_id=letter),
                    })
            print('get_enc_files: passing %s' % passing_numbers)
        with open('emails.json', 'w+') as f:
            f.write(json.dumps(result))
        return checked

    async def decrypt_enc_files(self, ids: list = None):
        """Декодирование файлов, которые скачали через get_enc_files
           дальше надо идти в test_drafts
        """
        folder = os.path.join(settings.ROOT_FOLDER, 'tmp')
        for filename in os.listdir(folder):
            if not filename.endswith('.enc'):
                continue
            if '__' not in filename:
                continue
            letter_id = int(filename.split('__')[0])
            if isinstance(ids, (list, tuple)) and letter_id not in ids:
                print('file is not new %s, passed' % letter_id)
                continue

            dest = os.path.join(folder, filename)
            print('enc_file: %s' % dest)
            decrypted = '%s' % dest[:-4]
            # Йобаный сертификат требует подтверждения с клавы
            cmd = '%s -decr "%s" "%s"' % (settings.CRYPT_CMD, dest, decrypted)
            print(cmd)
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, shell=True)
            time.sleep(5)
            p.communicate(input=b'%s\n' % settings.CRYPT_PASSWD)
            is_decrypted = os.path.exists(dest.replace('.enc', ''))
            decrypted_result = '' if is_decrypted else 'not '
            alert_msg = 'DRAFTS: try to decrypt file %s, file is %sdecrypted' % (filename, decrypted_result)
