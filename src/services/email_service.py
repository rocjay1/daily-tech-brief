"""
Email service module for generating and sending daily brief emails.

This module provides the EmailService class which handles:
- Generating HTML content for daily briefs
- Rendering sections for platform updates and blog posts
- Sending emails via SMTP
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List
from src.models import Article

logger = logging.getLogger(__name__)


class EmailService:
    """Service for handling email generation and sending."""

    _EMAIL_STYLES = {
        "body": "font-family: 'Segoe UI', sans-serif; color: #333; line-height: 1.6;",
        "container": "max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 8px;",
        "header": "background-color: #4b2c92; padding: 20px; text-align: center; color: white;",
        "header_h2": "margin:0;",
        "header_p": "margin:5px 0 0; opacity: 0.9;",
        "section": "padding: 20px;",
        "section_h3": "border-bottom: 2px solid #4b2c92; padding-bottom: 5px; margin-top: 30px;",
        "article": "margin-bottom: 25px; border-bottom: 1px solid #eee; padding-bottom: 15px;",
        "source": "font-size: 11px; font-weight: bold; color: #666; text-transform: uppercase;",
        "article_h3": "margin: 5px 0; font-size: 18px;",
        "link": "text-decoration: none; color: #0078D4;",
        "desc": "font-size: 14px; color: #444; margin-top: 5px;",
    }

    def __init__(
        self, smtp_server: str, smtp_port: int, sender_email: str, sender_password: str
    ):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password

    def _render_section(self, title: str, items: List[Article]) -> str:
        """Renders a section of the email."""
        if not items:
            return ""

        section_html = f"<h3 style='{self._EMAIL_STYLES['section_h3']}'>{title}</h3>"
        for item in items:
            description = (
                f"<b>Why it matters:</b> {item.get('reason', '')}"
                f"<br><br>{item['summary']}"
            )
            section_html += f"""
            <div style="{self._EMAIL_STYLES['article']}">
                <span style="{self._EMAIL_STYLES['source']}">{item['source']}</span>
                <h3 style="{self._EMAIL_STYLES['article_h3']}">
                    <a href="{item['link']}"
                       style="{self._EMAIL_STYLES['link']}">{item['title']}</a>
                </h3>
                <p style="{self._EMAIL_STYLES['desc']}">{description}</p>
            </div>
            """
        return section_html

    def generate_email_html(
        self, platform_articles: List[Article], blog_articles: List[Article]
    ) -> str:
        """Generates the HTML content for the email."""
        total_articles = len(platform_articles) + len(blog_articles)
        html_content = f"""
        <html>
        <body style="{self._EMAIL_STYLES['body']}">
            <div style="{self._EMAIL_STYLES['container']}">
                <div style="{self._EMAIL_STYLES['header']}">
                    <h2 style="{self._EMAIL_STYLES['header_h2']}">🚀 Daily Brief</h2>
                    <p style="{self._EMAIL_STYLES['header_p']}">Top {total_articles} Stories</p>
                </div>
                <div style="{self._EMAIL_STYLES['section']}">
        """

        html_content += self._render_section("Platform Updates", platform_articles)
        html_content += self._render_section("Blog Posts", blog_articles)

        html_content += "</div></div></body></html>"
        return html_content

    def send_email(
        self,
        recipient: str,
        platform_articles: List[Article],
        blog_articles: List[Article],
    ) -> None:
        """Formats and sends the daily brief via email."""
        total_articles = len(platform_articles) + len(blog_articles)
        if total_articles == 0:
            logger.info("No articles to send.")
            return

        html_content = self.generate_email_html(platform_articles, blog_articles)

        msg = MIMEMultipart()
        msg["From"] = self.sender_email
        msg["To"] = recipient
        msg["Subject"] = f"Daily Brief: {total_articles} Updates"
        msg.attach(MIMEText(html_content, "html"))

        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.sender_email, self.sender_password)
            server.send_message(msg)
            server.quit()
            logger.info("Email sent.")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Email failed: %s", e)
