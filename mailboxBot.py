import config
from errbot import BotPlugin, botcmd
from imaplib import IMAP4_SSL, IMAP4
import logging
from email.mime.text import MIMEText
from email.parser import Parser
from smtplib import SMTP, SMTPException


class MailboxBot(BotPlugin):
    def __init__(self):
        super(MailboxBot, self).__init__()
        self.queue = {}

    def activate(self):
        super(MailboxBot, self).activate()
        self.start_poller(config.IMAP_POLL_DELTA, self.imap_callback_message)

    def callback_message(self, conn, mess):
        body = mess.getBody()
        if config.MENTION_DELIM in body:
            mention, text = body.split(config.MENTION_DELIM, 1)
            room = mess.getMuckRoom()

            if room:
                sender = mess.getMuckNick()
            else:
                sender = mess.getFrom()

            nicks = conn.get_members(room)
            if not room or mention not in list(nicks):
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
        cmd = args[0]
        logging.debug(cmd)
        if cmd is 'add':
            pass
        elif cmd is 'del':
            pass
        elif cmd is 'list':
            return config.MAILBOXES
        else:
            return 'mailboxes (add|del|list)'

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
        if mailbox in config.MAILBOXES:
            relay = config.MAILBOXES[mailbox]['relay']
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
        text = '{}: {}'.format(sender, message)

        try:
            with SMTP(config.SMTP_SERVER) as smtp:
                smtp.starttls()
                smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)

                email = MIMEText('')
                email['From'] = config.SMTP_FROM
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
        try:
            imap = IMAP4_SSL(config.IMAP_SERVER)
            imap.login(config.IMAP_USERNAME, config.IMAP_PASSWORD)
            imap.select()

            new = imap.search(None, 'UNSEEN')[1][0].decode('utf-8')
            if new:
                for emailid in new.split(' '):
                    email = imap.fetch(emailid, '(RFC822)')[1][0][1]
                    email = email.decode('utf-8')
                    email = Parser().parsestr(email)

                    sender = email['From']
                    subject = email['Subject']

                    if config.MENTION_DELIM in subject:
                        mention, text = subject.split(': ', 1)
                        self.relay_message(mention, sender, text)

            imap.close()
            imap.logout()
        except IMAP4.error as err:
            logging.debug('IMAP4.error: {}'.format(err))
