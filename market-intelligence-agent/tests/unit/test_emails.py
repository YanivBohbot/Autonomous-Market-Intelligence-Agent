from email import policy
from email.parser import BytesParser

from app.agent.tools import emails


class FakeSesClient:
    def __init__(self):
        self.send_email_calls = []
        self.send_raw_email_calls = []

    def send_email(self, **kwargs):
        self.send_email_calls.append(kwargs)
        return {"MessageId": "plain-1"}

    def send_raw_email(self, **kwargs):
        self.send_raw_email_calls.append(kwargs)
        return {"MessageId": "raw-1"}


def test_plain_email_keeps_structured_ses_path(monkeypatch):
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": "Report", "body": "Body"
    })
    assert "MessageId" in result
    assert len(client.send_email_calls) == 1
    assert client.send_raw_email_calls == []


def test_attachment_uses_raw_mime_email(tmp_path, monkeypatch):
    report = tmp_path / "margaret-collins-portfolio-brief-2026-10-06.xlsx"
    report.write_bytes(b"xlsx bytes")
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    seen = []
    monkeypatch.setattr(
        emails,
        "resolve_generated_report",
        lambda filename: seen.append(filename) or report,
    )
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)

    emails.send_email_tool.invoke({
        "recipient": "margaret@example.com",
        "subject": "Portfolio report",
        "body": "Attached.",
        "attachment_filename": report.name,
    })

    raw = client.send_raw_email_calls[0]["RawMessage"]["Data"]
    message = BytesParser(policy=policy.default).parsebytes(raw)
    attachment = next(message.iter_attachments())
    assert seen == [report.name]
    assert message["To"] == "margaret@example.com"
    assert attachment.get_filename() == report.name
    assert attachment.get_content() == b"xlsx bytes"


def test_simulation_names_the_validated_attachment(tmp_path, monkeypatch):
    report = tmp_path / "margaret-collins-portfolio-brief-2026-10-06.xlsx"
    report.write_bytes(b"report")
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "placeholder@example.com")
    monkeypatch.setattr(emails, "resolve_generated_report", lambda filename: report)
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": "Report", "body": "Attached",
        "attachment_filename": report.name,
    })
    assert report.name in result


def test_resolution_failure_blocks_before_ses(monkeypatch):
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(
        emails, "resolve_generated_report",
        lambda filename: (_ for _ in ()).throw(ValueError("not generated")),
    )
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": "Report", "body": "Attached",
        "attachment_filename": "jane-doe-portfolio-brief.xlsx",
    })
    assert result == "Email blocked: not generated"
    assert client.send_email_calls == client.send_raw_email_calls == []


def test_oversized_raw_message_blocks_before_ses(tmp_path, monkeypatch):
    report = tmp_path / "margaret-collins-portfolio-brief.xlsx"
    report.write_bytes(b"large")
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(emails, "resolve_generated_report", lambda filename: report)
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)
    monkeypatch.setattr(emails, "MAX_RAW_EMAIL_BYTES", 1)
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": "Report", "body": "Attached",
        "attachment_filename": report.name,
    })
    assert "10,000,000 bytes" in result
    assert client.send_raw_email_calls == []


def test_attachment_field_is_optional():
    parsed = emails.EmailInput(recipient="margaret@example.com", subject="Hi", body="Body")
    assert parsed.attachment_filename is None


import pytest


@pytest.mark.parametrize("subject,body", [("", "Body"), ("Hi", ""), ("  ", "Body"), ("Hi", " \n ")])
def test_empty_subject_or_body_is_refused_and_nothing_is_sent(monkeypatch, subject, body):
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": subject, "body": body
    })
    assert result.startswith("Email blocked")
    assert client.send_email_calls == [] and client.send_raw_email_calls == []


def test_ses_rejection_is_reported_as_permanent(monkeypatch):
    from botocore.exceptions import ClientError

    class RejectingClient:
        def send_email(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "MessageRejected", "Message": "Email address is not verified."}},
                "SendEmail",
            )

    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(emails, "_create_ses_client", lambda: RejectingClient())
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": "Report", "body": "Body"
    })
    assert result.startswith("Erreur SES (MessageRejected)")
    assert "permanent" in result.lower() and "do not retry" in result.lower()


def test_markdown_is_stripped_from_the_plain_text_body(monkeypatch):
    """Live 2026-10-12: even with the prompt rule, the model wrote
    "### Holdings Breakdown:" and "**Total**" into a plain-text email."""
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)
    emails.send_email_tool.invoke({
        "recipient": "margaret@example.com",
        "subject": "Report",
        "body": "### Holdings Breakdown:\n- **NVDA**: 400 shares\n## Total\n**$156,532**",
    })
    sent = client.send_email_calls[0]["Message"]["Body"]["Text"]["Data"]
    assert sent == "Holdings Breakdown:\n- NVDA: 400 shares\nTotal\n$156,532"


def test_plain_text_helper_keeps_ordinary_text_untouched():
    text = "Dear Margaret,\n\n- NVDA: 58.6% of the portfolio\nC# and 3 * 4 stay as they are."
    assert emails.plain_text_body(text) == text
