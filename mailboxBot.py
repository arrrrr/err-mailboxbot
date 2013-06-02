from errbot import BotPlugin, botcmd
from imaplib import IMAP4_SSL, IMAP4
import logging
from email.mime.text import MIMEText
from email.parser import Parser
from smtplib import SMTP, SMTPException


class MailboxBot(BotPlugin):
    def get_configuration_template(self):
        return {'MENTION_DELIM': ': ',
                'SMTP_SERVER': 'server',
                'SMTP_USERNAME': 'username',
                'SMTP_PASSWORD': 'password',
                'SMTP_FROM': 'addr',
                'IMAP_SERVER': 'server',
                'IMAP_USERNAME': 'username',
                'IMAP_PASSWORD': 'password',
                'IMAP_POLL_DELTA': 60,
                'MAILBOXES': {}}

    def check_configuration(self, configuration):
        pass

    def __init__(self):
        super(MailboxBot, self).__init__()
        self.queue = {}

    def activate(self):
        super(MailboxBot, self).activate()
        delta = self.config['IMAP_POLL_DELTA']
        self.start_poller(delta, self.imap_callback_message)

    def callback_message(self, conn, mess):
        delim = self.config['MENTION_DELIM']
        body = mess.getBody()
        if delim in body:
            mention, text = body.split(delim, 1)
            room = mess.getMuckRoom()

            if room:
                sender = mess.getMuckNick()
            else:
                sender = mess.getFrom()

            nicks = conn.get_members(room)

            if '@' in mention:
                if '/' in mention:
                    self.xmpp_message(mention, sender, text)
                else:
                    self.smtp_message(mention, sender, text)
            elif not room or mention not in list(nicks):
                self.relay_message(mention, sender, text)

    @botcmd
    def mail(self, mess, args):
        if args:
            user = args
        elif mess.getMuckNick():
            user = mess.getMuckNick()
        else:
            user = mess.getFrom()

        messages = self.get_queued_messages(user)
        self.clear_queued_messages(user)

        if not messages:
            return 'No mail for {}'.format(user)
        else:
            return '\n'.join(messages)

    @botcmd(split_args_with=' ')
    def mailboxes(self, mess, args):
        configuration = self.config
        mailboxes = configuration['MAILBOXES']

        cmd, args = args[0], args[1:]
        if cmd == 'add':
            if len(args) == 2:
                name, relay = args
                mailboxes[name] = {'relay': relay}
                reply = 'added'
            else:
                reply = 'mailboxes add name relay'
        elif cmd == 'del':
            if len(args) == 1:
                name = args[0]
                mailboxes[name] = {}
                reply = 'deleted'
            else:
                reply = 'mailboxes del name'
        elif cmd == 'list':
            reply = mailboxes
        else:
            reply = 'mailboxes [add|del|list] ...'

        configuration['MAILBOXES'] = mailboxes
        self.configure(configuration)

        return reply

    def get_queued_messages(self, user):
        messages = []
        if user in self.queue:
            for message in self.queue[user]:
                if message.getMuckNick():
                    sender = message.getMuckNick()
                else:
                    sender = message.getFrom()

                text = message.getBody()
                messages.append('{}: {}'.format(sender, text))

        return messages

    def relay_message(self, mailbox, sender, message):
        mailboxes = self.config['MAILBOXES']
        if mailbox in mailboxes:
            relay = mailboxes[mailbox]['relay']
            if not relay:
                self.queue_message(mailbox, sender, message)
            elif '/' in relay:
                self.xmpp_message(relay, sender, message)
            else:
                self.smtp_message(relay, sender, message)
        else:
            self.queue_message(mailbox, sender, message)

    def xmpp_message(self, jid, sender, message):
        text = '{}: {}'.format(sender, message)
        self.send(jid, text)

    def smtp_message(self, to, sender, message):
        username = self.config['SMTP_USERNAME']
        password = self.config['SMTP_PASSWORD']
        text = '{}: {}'.format(sender, message)

        try:
            with SMTP(self.config['SMTP_SERVER']) as smtp:
                smtp.starttls()
                smtp.login(username, password)

                email = MIMEText('')
                email['From'] = self.config['SMTP_FROM']
                email['To'] = to
                email['Subject'] = text

                smtp.send_message(email)
        except SMTPException as err:
            logging.debug('SMTPException: {}'.format(err))

    def queue_message(self, mailbox, sender, message):
        text = '{}: {}'.format(sender, message)

        if mailbox not in self.queue:
            self.queue[mailbox] = []
        self.queue[mailbox].append(text)

    def clear_queued_messages(self, user):
        self.queue[user] = []

    def imap_callback_message(self):
        username = self.config['IMAP_USERNAME']
        password = self.config['IMAP_PASSWORD']

        try:
            imap = IMAP4_SSL(self.config['IMAP_SERVER'])
            imap.login(username, password)
            imap.select()

            new = imap.search(None, 'UNSEEN')[1][0].decode('utf-8')
            if new:
                for emailid in new.split(' '):
                    email = imap.fetch(emailid, '(RFC822)')[1][0][1]
                    email = email.decode('utf-8')
                    email = Parser().parsestr(email)

                    sender = email['From']
                    subject = email['Subject']

                    if self.config['MENTION_DELIM'] in subject:
                        mention, text = subject.split(': ', 1)
                        self.relay_message(mention, sender, text)

            imap.close()
            imap.logout()
        except IMAP4.error as err:
            logging.debug('IMAP4.error: {}'.format(err))
