"""
LogisticsManager Telegram Bot - Отдельный сервис для уведомлений
Railway Service #2: Только Telegram бот, читает из той же PostgreSQL
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from sqlalchemy import create_engine, text, Column, Integer, String, DateTime, Boolean, Numeric, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.pool import NullPool

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logger.error("DATABASE_URL not set!")
    DATABASE_URL = "postgresql://postgres:ZMhXQDvRXVJFDfoAvccbEndHRbKheqXM@shuttle.proxy.rlwy.net:41263/railway"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1119439099").strip()

logger.info(f"Database: {DATABASE_URL[:40]}..." if DATABASE_URL else "No DB")
logger.info(f"Bot token: {'✅' if TELEGRAM_TOKEN and len(TELEGRAM_TOKEN) > 20 else '❌'}")

# ==================== DATABASE MODELS (только для чтения) ====================

Base = declarative_base()

class CloudOrder(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True)
    order_number = Column(String(50))
    client_name = Column(String(200))
    container_count = Column(Integer, default=0)
    goods_type = Column(String(100))
    route = Column(String(200))
    status = Column(String(50))
    creation_date = Column(DateTime)
    departure_date = Column(DateTime)
    arrival_iran_date = Column(DateTime)
    eta_date = Column(DateTime)
    arrival_notice_date = Column(DateTime)
    tkm_date = Column(DateTime)
    notes = Column(Text)
    last_sync = Column(DateTime)
    
    containers = relationship("CloudContainer", lazy="selectin")

class CloudContainer(Base):
    __tablename__ = "containers"
    
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    container_number = Column(String(50))
    driver_first_name = Column(String(100))
    driver_last_name = Column(String(100))
    driver_company = Column(String(200))
    truck_number = Column(String(50))
    driver_iran_phone = Column(String(50))
    driver_turkmenistan_phone = Column(String(50))
    client_receiving_date = Column(DateTime)
    
    order = relationship("CloudOrder", back_populates="containers")

class CloudTask(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    description = Column(String(500))
    assigned_to = Column(String(100))
    status = Column(String(20))
    priority = Column(String(20))
    due_date = Column(DateTime)

# ==================== DATABASE CONNECTION ====================

engine = None
SessionLocal = None

def init_db():
    global engine, SessionLocal
    try:
        engine = create_engine(
            DATABASE_URL,
            poolclass=NullPool,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=300
        )
        SessionLocal = sessionmaker(bind=engine)
        
        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            logger.info(f"✅ DB connected: {result.scalar()}")
        return True
    except Exception as e:
        logger.error(f"❌ DB error: {e}")
        return False

def get_db():
    if SessionLocal:
        return SessionLocal()
    return None

# ==================== TELEGRAM COMMANDS ====================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = """
🚛 *Margiana Logistics Bot*

Доступные команды:
/report - Сводный отчет
/orders - Активные заказы
/drivers - Водители в рейсе
/status - Статус по направлениям
/search [номер] - Поиск заказа
/help - Помощь
    """
    await update.message.reply_text(welcome, parse_mode='Markdown')

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
*Как использовать:*

/report — текущая сводка
/search ORD-001 — найти заказ
/drivers — список водителей

*Статусы:*
🆕 New — Новый
🇨🇳 In Progress CHN — В Китае
🚢 In Transit CHN-IR — Морем
🇮🇷 In Progress IR — В Иране
🚛 In Transit IR-TKM — В Туркменистан
✅ Completed — Завершен
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db()
    if not db:
        await update.message.reply_text("❌ База данных недоступна")
        return
    
    try:
        total = db.query(CloudOrder).count()
        
        active_statuses = ["New", "In Progress CHN", "In Transit CHN-IR", 
                          "In Progress IR", "In Transit IR-TKM"]
        active = db.query(CloudOrder).filter(CloudOrder.status.in_(active_statuses)).count()
        
        # Count by status
        status_counts = {}
        for s in active_statuses + ["Completed"]:
            c = db.query(CloudOrder).filter(CloudOrder.status == s).count()
            if c > 0:
                status_counts[s] = c
        
        containers = db.query(CloudContainer).count()
        
        report = f"""
📊 *ОТЧЁТ — {datetime.now().strftime('%d.%m.%Y %H:%M')}*

*Всего:* {total} заказов, {containers} конт.
*Активных:* {active}

*По статусам:*
"""
        emoji_map = {
            "New": "🆕", "In Progress CHN": "🇨🇳", "In Transit CHN-IR": "🚢",
            "In Progress IR": "🇮🇷", "In Transit IR-TKM": "🚛", "Completed": "✅"
        }
        for s, c in status_counts.items():
            report += f"{emoji_map.get(s, '📋')} {s}: {c}\n"
        
        await update.message.reply_text(report, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Report error: {e}")
        await update.message.reply_text("❌ Ошибка генерации отчёта")
    finally:
        db.close()

async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db()
    if not db:
        await update.message.reply_text("❌ База данных недоступна")
        return
    
    try:
        active_statuses = ["New", "In Progress CHN", "In Transit CHN-IR", 
                          "In Progress IR", "In Transit IR-TKM"]
        orders = db.query(CloudOrder).filter(
            CloudOrder.status.in_(active_statuses)
        ).order_by(CloudOrder.creation_date.desc()).limit(10).all()
        
        if not orders:
            await update.message.reply_text("📭 Нет активных заказов")
            return
        
        msg = "📋 *АКТИВНЫЕ ЗАКАЗЫ:*\n\n"
        
        emoji_map = {
            "New": "🆕", "In Progress CHN": "🇨🇳", "In Transit CHN-IR": "🚢",
            "In Progress IR": "🇮🇷", "In Transit IR-TKM": "🚛"
        }
        
        for o in orders:
            cnt = len(o.containers) if o.containers else o.container_count
            msg += f"""{emoji_map.get(o.status, '📋')} *{o.order_number}*
👤 {o.client_name}
🚛 {cnt} конт. | {o.goods_type or '—'}
📍 {o.status}

"""
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Orders error: {e}")
        await update.message.reply_text("❌ Ошибка")
    finally:
        db.close()

async def cmd_drivers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db()
    if not db:
        await update.message.reply_text("❌ База данных недоступна")
        return
    
    try:
        from sqlalchemy import or_
        
        containers = db.query(CloudContainer).join(CloudOrder).filter(
            or_(
                CloudContainer.driver_first_name != None,
                CloudContainer.driver_last_name != None
            ),
            CloudOrder.status.in_(["In Transit CHN-IR", "In Transit IR-TKM", "In Progress IR"])
        ).limit(20).all()
        
        if not containers:
            await update.message.reply_text("📭 Нет водителей в рейсе")
            return
        
        msg = "🚛 *ВОДИТЕЛИ В РЕЙСЕ:*\n\n"
        
        for c in containers:
            pod = c.client_receiving_date.strftime('%d.%m') if c.client_receiving_date else "—"
            msg += f"""👤 *{c.driver_first_name or ''} {c.driver_last_name or ''}*
🏢 {c.driver_company or '—'}
🚛 {c.truck_number or '—'} | {c.container_number or '—'}
📞 IR: {c.driver_iran_phone or '—'}
📦 Заказ: {c.order.order_number if c.order else '—'}
🎯 POD: {pod}

"""
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Drivers error: {e}")
        await update.message.reply_text("❌ Ошибка")
    finally:
        db.close()

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db()
    if not db:
        await update.message.reply_text("❌ База данных недоступна")
        return
    
    try:
        msg = "🗺 *СТАТУС ПО НАПРАВЛЕНИЯМ*\n\n"
        
        # China
        new_cnt = db.query(CloudOrder).filter(CloudOrder.status == "New").count()
        chn_cnt = db.query(CloudOrder).filter(CloudOrder.status == "In Progress CHN").count()
        msg += f"*Китай:*\n🆕 Новые: {new_cnt}\n🇨🇳 В работе: {chn_cnt}\n\n"
        
        # Transit
        sea_cnt = db.query(CloudOrder).filter(CloudOrder.status == "In Transit CHN-IR").count()
        msg += f"*В пути:*\n🚢 Морем: {sea_cnt}\n\n"
        
        # Iran/TKM
        ir_cnt = db.query(CloudOrder).filter(CloudOrder.status == "In Progress IR").count()
        tkm_cnt = db.query(CloudOrder).filter(CloudOrder.status == "In Transit IR-TKM").count()
        msg += f"*Транзит:*\n🇮🇷 В Иране: {ir_cnt}\n🚛 В ТКМ: {tkm_cnt}\n\n"
        
        # Done
        done_cnt = db.query(CloudOrder).filter(CloudOrder.status == "Completed").count()
        msg += f"*Завершено:* ✅ {done_cnt}"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Status error: {e}")
        await update.message.reply_text("❌ Ошибка")
    finally:
        db.close()

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🔍 Укажите номер:\n/search ORD-001")
        return
    
    db = get_db()
    if not db:
        await update.message.reply_text("❌ База данных недоступна")
        return
    
    try:
        term = ' '.join(context.args)
        
        from sqlalchemy import or_
        orders = db.query(CloudOrder).filter(
            or_(
                CloudOrder.order_number.ilike(f'%{term}%'),
                CloudOrder.client_name.ilike(f'%{term}%')
            )
        ).limit(5).all()
        
        if not orders:
            await update.message.reply_text(f"🔍 '{term}' не найдено")
            return
        
        msg = f"🔍 *РЕЗУЛЬТАТЫ:* '{term}'\n\n"
        
        for o in orders:
            msg += f"""📋 *{o.order_number}*
👤 {o.client_name}
📍 {o.status}
🚛 {o.container_count} конт.
📝 {o.notes[:100] if o.notes else '—'}

"""
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text("❌ Ошибка")
    finally:
        db.close()

# ==================== MAIN ====================

def main():
    if not TELEGRAM_TOKEN or len(TELEGRAM_TOKEN) < 20:
        logger.error("Telegram token not configured!")
        return
    
    # Init DB
    if not init_db():
        logger.warning("Starting without database...")
    
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("report", cmd_report))
    application.add_handler(CommandHandler("orders", cmd_orders))
    application.add_handler(CommandHandler("drivers", cmd_drivers))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("search", cmd_search))
    
    # Run
    logger.info("🚀 Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
