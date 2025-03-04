# Copyright (C) 2011 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.topology import event
from ryu.topology.api import get_link
from path_finder import PathFinder


class SimpleSwitch13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13, self).__init__(*args, **kwargs)
        
        
        self.host_to_switch = {}
        self._init_host_to_switch()
        
        self.flow_capacity = {}
        self._init_flow_capacity()
        
        self.path_finder = PathFinder(self.flow_capacity, self.logger)
        
        self.links = {}
        
        self.datapaths = {}

    def _init_host_to_switch(self):
        """
        Reads `/tmp/host_info.json` and initializes the host_to_switch dictionary.
        """
        self.logger.info("Initializing host_to_switch dictionary from Mininet output...")

        # Percorso del file JSON generato da Mininet
        host_info_file = "/tmp/host_info.json"

        if not os.path.exists(host_info_file):
            self.logger.error(f"Host info file not found: {host_info_file}")
            return False

        try:
            with open(host_info_file, "r") as f:
                host_info: dict = json.load(f)

             # Popoliamo la mappa usando il MAC come chiave e salvando anche il nome dell'host
            for host_name, details in host_info.items():
                mac = details["mac"]
                self.host_to_switch[mac] = {
                    "name": host_name,
                    "connected_switch": details["connected_switch"],
                    "src_port": details["src_port"]
                }

            self.logger.info(f"Host-to-switch mapping initialized: {self.host_to_switch}")
            return True

        except json.JSONDecodeError:
            self.logger.error("Error decoding JSON file. Ensure Mininet has generated the file correctly.")
            return False

        except Exception as e:
            self.logger.error(f"Unexpected error reading host info file: {e}")
            return False
        
    def _init_flow_capacity(self):
        """
        Initializes the flow capacity dictionary based on bandwidth info from switch_links_info.json
        """
        self.logger.info("Initializing flow capacity dictionary...")

        # Read the JSON file
        try:
            with open("/tmp/switch_links_info.json", "r") as f:
                switch_links = json.load(f)
        except FileNotFoundError:
            self.logger.error("switch_links_info.json not found")
            return
        except json.JSONDecodeError:
            self.logger.error("Error decoding switch_links_info.json")
            return
        
        self.logger.info(f"Switch links info: {switch_links}")

        # Process each link
        for link_str, info in switch_links.items():
            # Parse switches from string like "s1-s2"
            sw1, sw2 = link_str.split("-")
            sw1_id = int(sw1.lstrip("s"))
            sw2_id = int(sw2.lstrip("s"))
            
            # Get bandwidth, default to 10 if not specified
            bw = info.get("bandwidth", 10)

            # Add both directions to flow capacity
            self.flow_capacity[(sw1_id, sw2_id)] = bw
            self.flow_capacity[(sw2_id, sw1_id)] = bw

        self.logger.info(f"Flow capacities initialized: {self.flow_capacity}")

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath  # Add datapath
            self.logger.info(f"Switch connected: dpid={datapath.id}")
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)  # Remove datapath
            self.logger.info(f"Switch disconnected: dpid={datapath.id}")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id  # Datapath ID of the switch
        self.logger.info(f"Switch connected: dpid={dpid}")
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Default rule to handle all packets
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    @set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        old_links = dict(self.links)
        # self.logger.info(f"Link added event: {ev.link.to_dict()}")
        # self.logger.info(f"Link added event: {ev.link.src.dpid} -> {ev.link.dst.dpid}")
        self._get_topology_data()
        # if old_links != self.links:
            # self.logger.info(f"Link added. Updated links: {self.links}")
            # self.logger.info(f"Link added. Updated links:")
            # pprint(self.links)
    
    def _get_topology_data(self):
        """
        Aggiorna i dati della topologia raccogliendo informazioni da get_switch() e get_link().
        """
        
        # Resetta i dizionari
        self.links.clear()
        
        
        # Ottieni i dati sui link
        link_list = get_link(self, None)
        for link in link_list:
            src_dpid = int(link.src.dpid)
            dst_dpid = int(link.dst.dpid)
            src_port_no = int(link.src.port_no)
            dst_port_no = int(link.dst.port_no)

            # Mappa i link nei dizionari
            self.links[(src_dpid, dst_dpid)] = {
                "src_port": src_port_no,
                "dst_port": dst_port_no,
                "src_hw_addr": link.src.hw_addr,
                "dst_hw_addr": link.dst.hw_addr,
            }

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    def allocate_flow(self, src_mac, dst_mac, msg_buffer_id = None):
        """
        Allocate a flow between two switches with a given bandwidth.
        :param src: Source switch ID.
        :param dst: Destination switch ID.
        :param bandwidth: Required bandwidth.
        :return: True if the flow was allocated, False otherwise.
        """
        # Controlla se src_mac e dst_mac esistono nel mapping host_to_switch
        if src_mac not in self.host_to_switch or dst_mac not in self.host_to_switch:
            self.logger.error(f"Host not found: {src_mac} -> {dst_mac}")
            return False

        src_details = self.host_to_switch[src_mac]
        dst_details = self.host_to_switch[dst_mac]

        # Converti la stringa dello switch (es. "s1") in dpid (int)
        src_dpid = int(src_details["connected_switch"].lstrip("s"))
        dst_dpid = int(dst_details["connected_switch"].lstrip("s"))

        src_datapath = self.datapaths.get(src_dpid)
        if src_datapath is None:
            self.logger.error(f"Datapath not found for dpid: {src_dpid}")
            return False

        dst_datapath = self.datapaths.get(dst_dpid)
        if dst_datapath is None:
            self.logger.error(f"Datapath not found for dpid: {dst_dpid}")
            return False

        # Crea i dizionari per gli switch se necessario
        src_switch = {"dpid": src_dpid}
        dst_switch = {"dpid": dst_dpid}
        
        path, available_bandwidth = self.path_finder.find_max_bandwidth_path(src_switch, dst_switch)
        if not path:
            self.logger.error("No path found with sufficient bandwidth.")
            return False
        
        src_port = self.host_to_switch[src_mac]["src_port"]
        dst_port = self.host_to_switch[dst_mac]["src_port"]
        
        self.install_path_flows(path, src_mac, dst_mac, src_port, dst_port, msg_buffer_id)
        self.install_path_flows(path[::-1], dst_mac, src_mac, dst_port, src_port, msg_buffer_id)
        
        self.logger.info(f"Flow allocated: {src_mac} -> {dst_mac}, path: {path}")

        return True
    
    
    def install_path_flows(self, path, src_mac, dst_mac, src_port, dst_port, msg_buffer_id=None):
        """
        Installs flow rules along the given path.
        Args:
            path (list): List of switch IDs in the path.
            src_mac (str): Source MAC address.
            dst_mac (str): Destination MAC address.
            src_port (int): Source port.
            dst_port (int): Destination port.
        """
        for i in range(len(path)):
            datapath = self.get_datapath(path[i])
            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto

            try:
                if i == 0:
                    self.logger.info(f"First switch: {path[i]} -> {path[i + 1]}")
                    # First switch: match src_mac and forward to the next switch
                    out_port = self.links[(path[i], path[i + 1])]["src_port"]
                    match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac, in_port=src_port)
                elif i == len(path) - 1:
                    self.logger.info(f"Last switch: {path[i]} -> host B")
                    # Last switch: forward to destination port
                    out_port = dst_port
                    match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                else:
                    self.logger.info(f"Intermediate switch: {path[i]} -> {path[i + 1]}")
                    # Intermediate switches
                    out_port = self.links[(path[i], path[i + 1])]["src_port"]
                    match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)

               
                actions = [parser.OFPActionOutput(out_port)]
                if msg_buffer_id:
                    self.add_flow(datapath, 1, match, actions, msg_buffer_id)
                else:
                    self.add_flow(datapath, 1, match, actions)

            except KeyError:
                self.logger.error(f"Link not found: {path[i]} -> {path[i + 1]}")
                return

        self.logger.info(f"Flow rules installed along path: {path}")

    def get_datapath(self, switch_id):
        """
        Maps a switch ID to its datapath object.

        Args:
            switch_id (str): Switch ID.

        Returns:
            datapath: The OpenFlow datapath object for the switch.
        """        
        return self.datapaths[switch_id]
    
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """
        Handles the PacketIn event to learn host locations and forward packets.
        Args:
            ev: The event object containing the packet and metadata.
        """
        
        msg = ev.msg
        dp = msg.datapath
        dpid = dp.id
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        
        if eth.ethertype in [ether_types.ETH_TYPE_LLDP, ether_types.ETH_TYPE_IPV6]:
            return  # Ignore LLDP and IPv6 packets 
        
        src = eth.src
        dst = eth.dst
    
        self.logger.info(f"PacketIn received: {eth.src} -> {eth.dst} on Switch {dpid}, Port {in_port}")
        

        # learn a mac address to avoid FLOOD next time.

        out_port = self.host_to_switch[dst]["src_port"] if dst in self.host_to_switch else ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:
            # verify if we have a valid buffer_id, if yes avoid to send both
            # flow_mod & packet_out
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.allocate_flow(src, dst, msg.buffer_id)
                return
            else:
                self.allocate_flow(src, dst)
            
            
            # if msg.buffer_id != ofproto.OFP_NO_BUFFER:
            #     self.add_flow(datapath, 1, match, actions, src, dst, msg.buffer_id)
            #     return
            # else:
            #     self.add_flow(datapath, 1, match, actions, src, dst)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)
