import socket
import uuid
import json
import httpx
from datetime import datetime, timedelta
from typing import List
import os
import logging
import asyncio

from cat.discovery.model.node_info import NodeInfo
from cat.discovery.model.update_message import UpdateMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DISCOVERY_PORT = int(os.getenv("DISCOVERY_PORT", 8765))
MULTICAST_GROUP = os.getenv("MULTICAST_GROUP", "224.1.1.1")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", 30))
NODE_TIMEOUT = int(os.getenv("NODE_TIMEOUT", 90))
UPDATE_PROPAGATION_TIMEOUT = int(os.getenv("UPDATE_PROPAGATION_TIMEOUT", 10))

class NetworkDiscovery:
    def __init__(self, node_id: str = None, host: str = "0.0.0.0", port: int = 8000):
        self.node_id = node_id or str(uuid.uuid4())
        self.host = host
        self.port = port
        self.nodes = {}
        self.processed_updates = set()
        self.running = False
        self.sock = None
    
    async def start(self):
        """Start the network discovery service."""
        self.running = True
        
        # Create multicast socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', DISCOVERY_PORT))
        
        # Join multicast group
        mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton(self.host)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.sock.setblocking(False)
        
        # Start background tasks
        asyncio.create_task(self._heartbeat_sender())
        asyncio.create_task(self._heartbeat_receiver())
        asyncio.create_task(self._cleanup_dead_nodes())
        
        logger.info(f"Network discovery started on {self.host}:{self.port} with node ID {self.node_id}")
        
    async def stop(self):
        """Stop the network discovery service."""
        self.running = False
        if self.sock:
            self.sock.close()
            self.sock = None
        logger.info("Network discovery stopped for node ID {self.node_id}")
    
    async def _heartbeat_sender(self):
        """Send periodic heartbeat messages"""
        while self.running:
            try:
                message = {
                    'type': 'heartbeat',
                    'node_id': self.node_id,
                    'host': self.host,
                    'port': self.port,
                    'timestamp': datetime.now().isoformat(),
                    'version': '1.0.0'
                }
                
                data = json.dumps(message).encode('utf-8')
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                sock.sendto(data, (MULTICAST_GROUP, DISCOVERY_PORT))
                sock.close()
                
                await asyncio.sleep(HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.error(f"Error sending heartbeat: {e}")
                await asyncio.sleep(5)
                
    async def _heartbeat_receiver(self):
        """Receive and process heartbeat messages"""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                message = json.loads(data.decode('utf-8'))
                
                if message['type'] == 'heartbeat' and message['node_id'] != self.node_id:
                    node_info = NodeInfo(
                        node_id=message['node_id'],
                        host=message['host'],
                        port=message['port'],
                        last_seen=datetime.now(),
                        metadata={'version': message.get('version', '1.0.0')}
                    )
                    
                    is_new_node = message['node_id'] not in self.nodes
                    self.nodes[message['node_id']] = node_info
                    
                    if is_new_node:
                        logger.info(f"Discovered new node: {message['node_id']} at {message['host']}:{message['port']}")
                
            except socket.error:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error receiving heartbeat: {e}")
                await asyncio.sleep(1)
    
    async def _cleanup_dead_nodes(self):
        """Remove nodes that haven't been seen recently"""
        while self.running:
            try:
                now = datetime.now()
                dead_nodes = [
                    node_id for node_id, node in self.nodes.items()
                    if now - node.last_seen > timedelta(seconds=NODE_TIMEOUT)
                ]
                
                for node_id in dead_nodes:
                    logger.info(f"Removing dead node: {node_id}")
                    del self.nodes[node_id]
                
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Error cleaning up dead nodes: {e}")
                await asyncio.sleep(30)
    
    def get_active_nodes(self) -> List[NodeInfo]:
        """Get list of currently active nodes"""
        return list(self.nodes.values())
    
    async def propagate_update(self, update_type: str, payload: dict):
        """Propagate an update to all known nodes"""
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
        
        # Send to all active nodes
        tasks = []
        for node in self.nodes.values():
            tasks.append(self._send_update_to_node(node, update_message))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            successful = sum(1 for r in results if not isinstance(r, Exception))
            logger.info(f"Update {update_id} propagated to {successful}/{len(tasks)} nodes")
        
        return update_id
    
    async def _send_update_to_node(self, node: NodeInfo, update: UpdateMessage):
        """Send update to a specific node"""
        try:
            async with httpx.AsyncClient(timeout=UPDATE_PROPAGATION_TIMEOUT) as client:
                url = f"http://{node.host}:{node.port}/api/updates"
                response = await client.post(url, json=update.to_dict())
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Failed to send update to {node.node_id}: {e}")
            return False
    
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
        
        # Propagate to other nodes (excluding source)
        await self._propagate_to_others(update)
        
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
            ccat = lizard.get_cheshire_cat(agent_id)
            if ccat:
                try:
                    logger.info(f"Updating LLM for agent {agent_id}")
                    # Avoid triggering another network update by temporarily disabling network propagation
                    original_lizard = getattr(ccat, 'lizard', None)
                    ccat.lizard = None
                    ccat.replace_llm(language_model_name, settings)
                    ccat.lizard = original_lizard
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
                    
                    action = "updated" if lizard.plugin_manager.plugin_exists(plugin_id) else "installed"
                    logger.info(f"Successfully {action} plugin {plugin_id} from network update")
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
    
    async def _propagate_to_others(self, update: UpdateMessage):
        """Propagate update to other nodes (excluding source)"""
        tasks = []
        for node in self.nodes.values():
            if node.node_id != update.source_node:
                tasks.append(self._send_update_to_node(node, update))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)