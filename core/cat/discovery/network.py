import uuid
import json
from datetime import datetime
from typing import List
import os
import logging
import asyncio

from cat.discovery.model.node_info import NodeInfo
from cat.discovery.model.update_message import UpdateMessage
from cat.db.database import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", 30))
NODE_TIMEOUT = int(os.getenv("NODE_TIMEOUT", 90))
UPDATE_PROPAGATION_TIMEOUT = int(os.getenv("UPDATE_PROPAGATION_TIMEOUT", 10))
REDIS_NODE_PREFIX = "cheshire:nodes:"
REDIS_UPDATES_CHANNEL = "cheshire:updates"

class NetworkDiscovery:
    def __init__(self, node_id: str = None, host: str = "0.0.0.0", port: int = 8000):
        self.node_id = node_id or str(uuid.uuid4())
        self.host = host
        self.port = port
        self.nodes = {}
        self.processed_updates = set()
        self.running = False
        self.redis = None
        self.pubsub = None
    
    async def start(self):
        """Start the network discovery service."""
        self.running = True
        
        # Initialize Redis connection
        self.redis = get_db()
        self.pubsub = self.redis.pubsub()
        self.pubsub.subscribe(REDIS_UPDATES_CHANNEL)

        # Start background tasks
        asyncio.create_task(self._heartbeat_sender())
        asyncio.create_task(self._update_receiver())
        asyncio.create_task(self._cleanup_dead_nodes())
        
        logger.info(f"Network discovery started on {self.host}:{self.port} with node ID {self.node_id}")
        
    async def stop(self):
        """Stop the network discovery service."""
        self.running = False
        
        # Remove node from Redis
        if self.redis:
            try:
                self.redis.delete(f"{REDIS_NODE_PREFIX}{self.node_id}")
            except Exception as e:
                logger.error(f"Error removing node from Redis: {e}")
        
        # Close pubsub connection
        if self.pubsub:
            try:
                self.pubsub.unsubscribe(REDIS_UPDATES_CHANNEL)
                self.pubsub.close()
                self.pubsub = None
            except Exception as e:
                logger.error(f"Error closing pubsub: {e}")
                
        logger.info(f"Network discovery stopped for node ID {self.node_id}")
    
    async def _heartbeat_sender(self):
        """Register node in Redis and update heartbeat"""
        while self.running:
            try:
                node_data = {
                    'node_id': self.node_id,
                    'host': self.host,
                    'port': self.port,
                    'timestamp': datetime.now().isoformat(),
                    'version': '1.0.0'
                }
                
                # Store node info with TTL
                node_key = f"{REDIS_NODE_PREFIX}{self.node_id}"
                self.redis.hset(node_key, mapping=node_data)
                self.redis.expire(node_key, NODE_TIMEOUT)
                
                # Update local nodes cache
                await self._refresh_nodes_cache()
                
                await asyncio.sleep(HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.error(f"Error sending heartbeat: {e}")
                await asyncio.sleep(5)
                
    async def _refresh_nodes_cache(self):
        """Refresh local nodes cache from Redis"""
        try:
            # Get all node keys
            node_keys = self.redis.keys(f"{REDIS_NODE_PREFIX}*")
            current_nodes = {}
            
            for key in node_keys:
                node_data = self.redis.hgetall(key)
                if node_data and node_data.get('node_id') != self.node_id:
                    node_info = NodeInfo(
                        node_id=node_data['node_id'],
                        host=node_data['host'],
                        port=int(node_data['port']),
                        last_seen=datetime.fromisoformat(node_data['timestamp']),
                        metadata={'version': node_data.get('version', '1.0.0')}
                    )
                    
                    is_new_node = node_data['node_id'] not in self.nodes
                    current_nodes[node_data['node_id']] = node_info
                    
                    if is_new_node:
                        logger.info(f"Discovered new node: {node_data['node_id']} at {node_data['host']}:{node_data['port']}")
            
            self.nodes = current_nodes
            
        except Exception as e:
            logger.error(f"Error refreshing nodes cache: {e}")

    async def _update_receiver(self):
        """Receive and process update messages via Redis pub/sub"""
        while self.running:
            try:
                message = self.pubsub.get_message(timeout=1.0)
                if message and message['type'] == 'message':
                    update_data = json.loads(message['data'])
                    update = UpdateMessage.from_dict(update_data)
                    await self.handle_received_update(update)
                await asyncio.sleep(0.1)  # Small delay to prevent busy waiting
                    
            except Exception as e:
                logger.error(f"Error receiving update: {e}")
                await asyncio.sleep(1)
    
    async def _cleanup_dead_nodes(self):
        """Remove expired nodes from Redis and local cache"""
        while self.running:
            try:
                # Redis automatically removes expired keys, so we just refresh our cache
                await self._refresh_nodes_cache()
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Error cleaning up dead nodes: {e}")
                await asyncio.sleep(30)
    
    def get_active_nodes(self) -> List[NodeInfo]:
        """Get list of currently active nodes"""
        return list(self.nodes.values())
    
    async def propagate_update(self, update_type: str, payload: dict):
        """Propagate an update to all known nodes via Redis pub/sub"""
        update_id = str(uuid.uuid4())
        
        # Mark as processed to avoid self-propagation
        self.processed_updates.add(update_id)
        
        update_message = UpdateMessage(
            update_id=update_id,
            update_type=update_type,
            payload=payload,
            timestamp=datetime.now(),
            source_node=self.node_id
        )
        
        try:
            # Publish update to Redis channel
            self.redis.publish(REDIS_UPDATES_CHANNEL, json.dumps(update_message.to_dict()))
            logger.info(f"Update {update_id} published to Redis channel")
        except Exception as e:
            logger.error(f"Failed to publish update {update_id}: {e}")
        
        return update_id
    
    
    async def handle_received_update(self, update: UpdateMessage) -> bool:
        """Handle an update received from another node"""
        # Check if we've already processed this update
        if update.update_id in self.processed_updates:
            return False
        
        # Mark as processed
        self.processed_updates.add(update.update_id)
        
        # Clean up old processed updates (keep last 1000)
        if len(self.processed_updates) > 1000:
            # Convert to list, sort by some criteria, keep recent ones
            # For simplicity, just clear old ones periodically
            pass
        
        logger.info(f"Processing update {update.update_id} of type {update.update_type} from {update.source_node}")
        
        # Handle specific update types
        if update.update_type == "llm_update":
            await self._handle_llm_update(update)
        elif update.update_type == "plugin_installed":
            await self._handle_plugin_installed(update)
        elif update.update_type == "plugin_uninstalled":
            await self._handle_plugin_uninstalled(update)
        
        
        return True
    
    async def _handle_llm_update(self, update: UpdateMessage):
        """Handle LLM update from another node"""
        try:
            payload = update.payload
            language_model_name = payload.get("language_model_name")
            settings = payload.get("settings")
            agent_id = payload.get("agent_id")
            
            logger.info(f"Received LLM update: {language_model_name} for agent {agent_id}")
            
            # Get Bill the Lizard instance to update the specific CheshireCat instance
            from cat.looking_glass.bill_the_lizard import BillTheLizard
            lizard = BillTheLizard()
            
            # Update the specific CheshireCat instance with the same agent_id
            ccat = lizard.get_cheshire_cat_from_db(agent_id)
            if ccat:
                try:
                    logger.info(f"Updating LLM for agent {agent_id}")
                    # Directly update the LLM configuration without triggering network propagation
                    # by using the same logic as replace_llm but skipping the network update part
                    from cat.adapters.factory_adapter import FactoryAdapter
                    from cat.factory.llm import LLMFactory
                    
                    adapter = FactoryAdapter(LLMFactory(ccat.plugin_manager))
                    adapter.upsert_factory_config_by_settings(ccat.id, language_model_name, settings)
                    
                    # Reload the LLM
                    ccat.load_language_model()
                    
                    # Recreate tools embeddings
                    ccat.plugin_manager.find_plugins()
                    
                    logger.info(f"Successfully updated LLM for agent {agent_id}")
                except Exception as e:
                    logger.error(f"Failed to update LLM for agent {agent_id}: {e}")
            else:
                logger.warning(f"Agent {agent_id} not found on this node")
            
        except Exception as e:
            logger.error(f"Error handling LLM update: {e}")
    
    async def _handle_plugin_installed(self, update: UpdateMessage):
        """Handle plugin installation from another node"""
        try:
            payload = update.payload
            plugin_url = payload.get("plugin_url")
            plugin_id = payload.get("plugin_id")
            
            logger.info(f"Received plugin installation update: {plugin_id} from {plugin_url}")
            
            # Get Bill the Lizard instance to install the plugin
            from cat.looking_glass.bill_the_lizard import BillTheLizard
            lizard = BillTheLizard()
            
            try:
                # Check if this is an uploaded plugin or registry plugin
                if plugin_url.startswith("upload://"):
                    # For uploaded plugins, force reload the plugin if it exists
                    filename = plugin_url.replace("upload://", "")
                    if lizard.plugin_manager.plugin_exists(plugin_id):
                        logger.info(f"Plugin {plugin_id} already exists, forcing reload due to upload on another node ('{filename}')")
                        # Force reload the plugin by calling find_plugins which rediscoveres all plugins
                        lizard.plugin_manager.find_plugins()
                        # Notify all CheshireCats about the plugin changes
                        lizard.notify_plugin_installed_local_only()
                    else:
                        logger.info(f"Plugin {plugin_id} was uploaded as '{filename}' on another node. Manual installation required.")
                else:
                    # For registry plugins, always install/update even if it exists
                    from cat.mad_hatter.registry import registry_download_plugin
                    tmp_plugin_path = await registry_download_plugin(plugin_url)
                    
                    # Temporarily disable network propagation to avoid infinite loops
                    original_callback = lizard.plugin_manager.on_finish_plugin_install_callback
                    lizard.plugin_manager.on_finish_plugin_install_callback = lambda plugin_id: lizard.notify_plugin_installed_local_only()
                    
                    # Install plugin (this will overwrite if it already exists)
                    lizard.plugin_manager.install_plugin(tmp_plugin_path)
                    
                    # Restore original callback
                    lizard.plugin_manager.on_finish_plugin_install_callback = original_callback
                    
                    logger.info(f"Successfully processed plugin {plugin_id} from network update")
            except Exception as e:
                logger.error(f"Failed to install/update plugin {plugin_id} from network update: {e}")
                
        except Exception as e:
            logger.error(f"Error handling plugin installation update: {e}")
    
    async def _handle_plugin_uninstalled(self, update: UpdateMessage):
        """Handle plugin uninstallation from another node"""
        try:
            payload = update.payload
            plugin_id = payload.get("plugin_id")
            
            logger.info(f"Received plugin uninstallation update: {plugin_id}")
            
            # Get Bill the Lizard instance to uninstall the plugin
            from cat.looking_glass.bill_the_lizard import BillTheLizard
            lizard = BillTheLizard()
            
            # Check if plugin exists before attempting uninstallation
            if lizard.plugin_manager.plugin_exists(plugin_id):
                try:
                    # Temporarily disable network propagation to avoid infinite loops
                    original_callback = lizard.plugin_manager.on_finish_plugin_uninstall_callback
                    lizard.plugin_manager.on_finish_plugin_uninstall_callback = lambda plugin_id: lizard.clean_up_plugin_uninstall_local_only(plugin_id)
                    
                    lizard.plugin_manager.uninstall_plugin(plugin_id)
                    
                    # Restore original callback
                    lizard.plugin_manager.on_finish_plugin_uninstall_callback = original_callback
                    
                    logger.info(f"Successfully uninstalled plugin {plugin_id} from network update")
                except Exception as e:
                    logger.error(f"Failed to uninstall plugin {plugin_id} from network update: {e}")
            else:
                logger.info(f"Plugin {plugin_id} not found, skipping uninstallation")
                
        except Exception as e:
            logger.error(f"Error handling plugin uninstallation update: {e}")
    
