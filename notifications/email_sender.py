"""
Email sender — sends the weekly research digest via Gmail SMTP.

Required environment variables:
    EMAIL_SENDER      your Gmail address (e.g. you@gmail.com)
    EMAIL_PASSWORD    Gmail App Password (16-char, NOT your real password)
                      Generate at: myaccount.google.com/apppasswords
    EMAIL_RECIPIENT   address to send the digest to (can be same as sender)

Gmail App Passwords work even with 2FA enabled and don't expose your
real password. They can be revoked at any time.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime


def send_digest_email(subject: str, markdown_body: str) -> None:
    """
    Send the digest as a nicely formatted HTML email.
    Falls back to plain text if HTML rendering fails.
    """
    sender = os.environ.get("EMAIL_SENDER", "").strip()
    password = os.environ.get("EMAIL_PASSWORD", "").strip()
    recipient = os.environ.get("EMAIL_RECIPIENT", "").strip()

    if not sender or not password or not recipient:
        raise RuntimeError(
            "Email not configured. Set EMAIL_SENDER, EMAIL_PASSWORD, and "
            "EMAIL_RECIPIENT as Windows environment variables.\n"
            "Generate a Gmail App Password at: myaccount.google.com/apppasswords"
        )

    html_body = _markdown_to_html(markdown_body)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg["X-Priority"] = "3"

    # Attach both plain text and HTML — email clients pick the best one
    msg.attach(MIMEText(_strip_markdown(markdown_body), "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())


def _strip_markdown(text: str) -> str:
    """Very basic markdown → plain text for the fallback part."""
    import re
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"^---+$", "─" * 40, text, flags=re.MULTILINE)
    return text


def _markdown_to_html(md: str) -> str:
    """Convert the digest markdown to clean HTML for the email."""
    import re

    lines = md.split("\n")
    html_lines = []

    for line in lines:
        # H1
        if line.startswith("# "):
            html_lines.append(f'<h1 style="color:#1a1a2e;font-family:Georgia,serif;">{line[2:]}</h1>')
        # H2
        elif line.startswith("## "):
            html_lines.append(f'<h2 style="color:#16213e;border-bottom:1px solid #ddd;padding-bottom:4px;">{line[3:]}</h2>')
        # H3
        elif line.startswith("### "):
            html_lines.append(f'<h3 style="color:#0f3460;">{line[4:]}</h3>')
        # Blockquote
        elif line.startswith("> "):
            html_lines.append(f'<blockquote style="border-left:4px solid #0f3460;margin:8px 0;padding-left:12px;color:#555;">{line[2:]}</blockquote>')
        # HR
        elif re.match(r"^---+$", line):
            html_lines.append('<hr style="border:none;border-top:1px solid #eee;margin:16px 0;">')
        # List item
        elif line.startswith("- "):
            html_lines.append(f'<li style="margin:4px 0;">{_inline_md(line[2:])}</li>')
        # Blank line
        elif line.strip() == "":
            html_lines.append("<br>")
        # Normal paragraph
        else:
            html_lines.append(f'<p style="margin:6px 0;">{_inline_md(line)}</p>')

    body = "\n".join(html_lines)

    return f"""
    <html>
    <body style="font-family:Arial,sans-serif;max-width:680px;margin:auto;
                 padding:24px;color:#222;background:#fafafa;">
        <div style="background:#fff;border-radius:8px;padding:24px;
                    box-shadow:0 2px 8px rgba(0,0,0,0.08);">
            {body}
            <p style="color:#999;font-size:12px;margin-top:24px;">
                Sent by your Research Recommendation Agent
            </p>
        </div>
    </body>
    </html>
    """


def _inline_md(text: str) -> str:
    """Handle bold, italic, and links inline."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" style="color:#0f3460;">\1</a>', text)
    return text
