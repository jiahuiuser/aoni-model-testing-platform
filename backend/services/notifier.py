"""
AONI 平台 — 邮件 (SMTP Email) 消息通知服务
取代原企微 Webhook 方式
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

from backend.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_SENDER

logger = logging.getLogger("aoni.notifier")


def send_email_notification(
    to_email: str,
    task_name: str,
    model_name: str,
    device_name: str,
    status: str,
    detail_msg: str = "",
    perf_summary: str = ""
) -> bool:
    """
    发送邮件通知消息 (支持 HTML 格式)
    :param to_email: 接收者邮箱地址
    :param task_name: 任务名称
    :param model_name: 测试模型名称
    :param device_name: 目标测试节点
    :param status: 状态 ('RUNNING', 'COMPLETED', 'FAILED')
    :param detail_msg: 详细描述或报错信息
    :param perf_summary: 性能结果摘要
    """
    if not to_email or "@" not in to_email:
        return False

    status_upper = status.upper()
    if status_upper in ("COMPLETED", "DONE"):
        status_text = "✅ 测试成功完成"
        badge_color = "#10b981"
    elif status_upper == "FAILED":
        status_text = "❌ 测试异常失败"
        badge_color = "#ef4444"
    elif status_upper == "RUNNING":
        status_text = "🚀 测试流水线启动"
        badge_color = "#3b82f6"
    else:
        status_text = f"ℹ️ 状态通知: {status}"
        badge_color = "#6b7280"

    subject = f"[AONI 算力评测] 任务通知: {task_name} ({status_text})"

    html_content = f"""
    <div style="font-family: Arial, 'Microsoft YaHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
        <div style="background-color: #1e293b; color: #ffffff; padding: 20px; text-align: center;">
            <h2 style="margin: 0; font-size: 20px;">📊 AONI 算力测试平台评测通知</h2>
        </div>
        <div style="padding: 24px; background-color: #ffffff; color: #334155;">
            <div style="margin-bottom: 16px;">
                <span style="display: inline-block; padding: 4px 12px; background-color: {badge_color}; color: #ffffff; font-weight: bold; border-radius: 4px; font-size: 14px;">
                    {status_text}
                </span>
            </div>
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px;">
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 0; color: #64748b; width: 100px;">任务名称：</td>
                    <td style="padding: 10px 0; font-weight: bold; color: #0f172a;">{task_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 0; color: #64748b;">测试模型：</td>
                    <td style="padding: 10px 0; font-weight: bold; color: #2563eb;">{model_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 0; color: #64748b;">目标节点：</td>
                    <td style="padding: 10px 0;">{device_name}</td>
                </tr>
                {f'<tr style="border-bottom: 1px solid #f1f5f9;"><td style="padding: 10px 0; color: #64748b;">核心指标：</td><td style="padding: 10px 0; color: #059669; font-weight: bold;">{perf_summary}</td></tr>' if perf_summary else ''}
            </table>
            {f'<div style="background-color: #f8fafc; border-left: 4px solid #94a3b8; padding: 12px; font-size: 13px; color: #475569; word-break: break-all;"><b>说明：</b> {detail_msg}</div>' if detail_msg else ''}
        </div>
        <div style="background-color: #f1f5f9; padding: 12px; text-align: center; font-size: 12px; color: #94a3b8;">
            此邮件由 AONI 模型测试平台自动发送，请勿直接回复。
        </div>
    </div>
    """

    smtp_host = SMTP_HOST or os.getenv("SMTP_HOST")
    smtp_port = SMTP_PORT or int(os.getenv("SMTP_PORT", "465"))
    smtp_user = SMTP_USER or os.getenv("SMTP_USER")
    smtp_pass = SMTP_PASS or os.getenv("SMTP_PASS")
    sender = SMTP_SENDER or smtp_user or "aoni_notifier@163.com"

    if not smtp_host or not smtp_user or not smtp_pass:
        logger.warning(f"SMTP 未配置账号信息，已跳过发送到 {to_email} (可于 .env 配置 SMTP_HOST/SMTP_USER/SMTP_PASS)")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = Header(f"AONI 测试平台 <{sender}>")
        msg["To"] = Header(to_email)
        msg["Subject"] = Header(subject, "utf-8")
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            server.starttls()

        server.login(smtp_user, smtp_pass)
        server.sendmail(sender, [to_email], msg.as_string())
        server.quit()
        logger.info(f"成功发送邮件通知给 [{to_email}]")
        return True
    except Exception as err:
        logger.error(f"发送邮件给 {to_email} 失败: {err}")
        return False
