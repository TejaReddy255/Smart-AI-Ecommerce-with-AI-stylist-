import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),'..')))
from config import settings

# from dotenv import load_dotenv

# load_dotenv()

def send_order_email(order, to_email, content):
    try:
        sender_email = settings.SMTP_USER
        sender_display_name = settings.SMTP_FROM
        sender_password = settings.SMTP_PASS
        smtp_server = settings.SMTP_HOST
        smtp_port = settings.SMTP_PORT

        # print(f'from: {sender_email}, to: {to_email}, smpt: {smtp_server}, port: {smtp_port}')

        if not sender_email or not sender_password:
            print("Email Configuration not found. Please set SENDER_USER and SMTP_PASS environment variables.")
            return False, "console"

        message = MIMEMultipart("alternative")
        message["Subject"] = content["subject"]
        message["From"] = formataddr((sender_display_name, sender_email))
        message["To"] = to_email
        message.attach(MIMEText(content["text"], "plain"))
        message.attach(MIMEText(content["html"], "html"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, message.as_string())

        print(f"Email sent successfully to {to_email}")
        return True, "smtp"

    except Exception as e:
        print(f"Error sending email: {e}")
        return False, "console"