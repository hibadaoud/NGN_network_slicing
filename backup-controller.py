import time
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4, ipv6
# from ryu.lib import hub  # <-- se non vuoi un monitor costante, commenta
from ryu.topology import event
from ryu.topology.api import get_switch, get_link, get_host
from ryu.app.wsgi import WSGIApplication

from flow_allocator_handler_REST import FlowRequestHandler
from path_finder import PathFinder

class FlowAllocator(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(FlowAllocator, self).__init__(*args, **kwargs)
        self.logger.setLevel("INFO")
        self.logger.info("Initializing FlowAllocator...")
        wsgi = kwargs['wsgi']
        wsgi.register(FlowRequestHandler, {'flow_allocator': self})
        self.logger.info("FlowRequestHandler registered!")

        # Strutture di dati
        self.switches = {}  # dpid -> {"ports": {}, "mac_to_port": {}}
        self.links = {}     # (src_dpid, dst_dpid) -> {... capacity, residual_bw...}
        self.hosts = {}     # mac -> {"dpid": ..., "port_no": ..., "ip": ...}

        self.datapaths = {}
        # Non avviamo un monitor costante: commentiamo se non serve
        # self.monitor_thread = hub.spawn(self._monitor)

        # PathFinder per calcolare percorsi con banda minima
        self.path_finder = PathFinder({}, self.logger)

    # ------------------------------------------------
    # 1) Stato switch e regola di default
    # ------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        dp = ev.datapath
        dpid = dp.id
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dpid] = dp
            self._init_switch(dpid)
            self.logger.info(f"Switch connected: dpid={dpid}")
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dpid, None)
            self.switches.pop(dpid, None)
            self.logger.info(f"Switch disconnected: dpid={dpid}")

    def _init_switch(self, dpid):
        self.switches[dpid] = {
            "ports": {},
            "mac_to_port": {}
        }

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, MAIN_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        dpid = dp.id
        parser = dp.ofproto_parser
        ofproto = dp.ofproto

        self.logger.info(f"Switch connected (Features): dpid={dpid}")
        # Regola di default -> invia tutto a controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)

    def add_flow(self, dp, priority, match, actions, buffer_id=None):
        parser = dp.ofproto_parser
        ofproto = dp.ofproto

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(
                datapath=dp,
                buffer_id=buffer_id,
                priority=priority,
                match=match,
                instructions=inst
            )
        else:
            mod = parser.OFPFlowMod(
                datapath=dp,
                priority=priority,
                match=match,
                instructions=inst
            )
        dp.send_msg(mod)

    # ------------------------------------------------
    # 2) Topologia (SwitchEnter, LinkAdd, LinkDelete)
    # ------------------------------------------------
    @set_ev_cls(event.EventSwitchEnter)
    def switch_enter_handler(self, ev):
        old_links = dict(self.links)
        self.logger.info(f"Switch entered: {ev.switch.dp.id}")
        self._get_topology_data()
        if old_links != self.links:
            self.logger.info(f"Switch added. Updated links: {self.links}")

    @set_ev_cls(event.EventLinkAdd)
    def link_add_handler(self, ev):
        old_links = dict(self.links)
        # self.logger.info(f"Link added event: {ev.link.to_dict()}")
        # self.logger.info(f"Link added event: {ev.link.src.dpid} -> {ev.link.dst.dpid}")
        self._get_topology_data()
        if old_links != self.links:
            self.logger.info(f"Link added. Updated links: {self.links}")

    @set_ev_cls(event.EventLinkDelete)
    def link_delete_handler(self, ev):
        self._get_topology_data()
        self.logger.info(f"Link deleted. Updated links: {self.links}")

    def _get_topology_data(self):
        """
        Aggiorna i dati della topologia raccogliendo informazioni da get_switch() e get_link().
        """
        # Resetta i dizionari
        self.switches.clear()
        self.links.clear()

        # Ottieni dati sugli switch
        sw_list = get_switch(self, None)
        for sw in sw_list:
            dpid = int(sw.dp.id)  # Converti il dpid in un intero per uniformità
            self.switches[dpid] = {"ports": {}, "links": {}}

            # Raccogli le porte dello switch
            for port in sw.ports:
                port_no = int(port.port_no)  # Porta come intero
                self.switches[dpid]["ports"][port_no] = {
                    "hw_addr": port.hw_addr,
                    "name": port.name,
                }

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

            # Aggiorna i link connessi nello switch sorgente
            self.switches[src_dpid]["links"][src_port_no] = {
                "dst_dpid": dst_dpid,
                "dst_port": dst_port_no,
            }

            # Aggiorna i link connessi nello switch di destinazione
            self.switches[dst_dpid]["links"][dst_port_no] = {
                "dst_dpid": src_dpid,
                "dst_port": src_port_no,
            }
        #  # Ottieni dati sugli host
        # host_list = get_host(self, None)
        # for host in host_list:
        #     mac = host.mac
        #     ip = host.ipv4 if host.ipv4 else host.ipv6  # Prendi IPv4, se non c'è usa IPv6
        #     dpid = int(host.port.dpid)
        #     port_no = int(host.port.port_no)

        #     # Mappa l'host nello switch
        #     self.switches[dpid]["hosts"][mac] = {
        #         "ip": ip,
        #         "port_no": port_no,
        #     }

        # Debug: Stampa i dizionari aggiornati
        self.logger.info("=== Topology Data ===")
        # self.logger.info(f"Switches: {self.switches}")
        # self.logger.info(f"Links: {self.links}")
        # self.logger.info(f"Hosts: {self.hosts}")


    # ------------------------------------------------
    # 3) Packet-In: Imparare MAC, IP, forwarding base
    # ------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        dpid = dp.id
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        src = eth.src
        dst = eth.dst

        # Protocolli L3
        arp_pkt = pkt.get_protocol(arp.arp)
        ipv4_pkt = pkt.get_protocol(ipv4.ipv4)
        ipv6_pkt = pkt.get_protocol(ipv6.ipv6)

        if arp_pkt:
            ip_src = arp_pkt.src_ip
            self.logger.info(f"ARP from IP={ip_src}, MAC={src}")
            if src not in self.hosts:
                self.hosts[src] = {
                    "dpid": dpid, "port_no": in_port, "ip": ip_src
                }
            else:
                self.hosts[src]["ip"] = ip_src

        elif ipv4_pkt:
            ip_src = ipv4_pkt.src
            self.logger.info(f"IPv4 from IP={ip_src}, MAC={src}")
            if src not in self.hosts:
                self.hosts[src] = {
                    "dpid": dpid, "port_no": in_port, "ip": ip_src
                }
            else:
                self.hosts[src]["ip"] = ip_src

        elif ipv6_pkt:
            ip_src = ipv6_pkt.src
            self.logger.info(f"IPv6 from IP={ip_src}, MAC={src}")
            if src not in self.hosts:
                self.hosts[src] = {
                    "dpid": dpid, "port_no": in_port, "ip": ip_src
                }
            else:
                self.hosts[src]["ip"] = ip_src

        # MAC-to-port
        self.switches[dpid]["mac_to_port"][src] = in_port
        if src not in self.hosts:
            self.hosts[src] = {"dpid": dpid, "port_no": in_port}

        # Se dst non noto => flood
        if dst not in self.hosts:
            out_ports = [
                p.port_no for p in dp.ports.values()
                if p.port_no != in_port
            ]
            actions = [parser.OFPActionOutput(port) for port in out_ports]
        else:
            dst_info = self.hosts[dst]
            if dst_info["dpid"] == dpid:
                out_port = self.switches[dpid]["mac_to_port"][dst]
            else:
                out_port = self.get_port_between_switches(dpid, dst_info["dpid"])
            actions = [parser.OFPActionOutput(out_port)]

        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )
        dp.send_msg(out)

    def get_port_between_switches(self, src_dpid, dst_dpid):
        link_info = self.links.get((src_dpid, dst_dpid), None)
        if link_info:
            return link_info["src_port"]
        return None

    # ------------------------------------------------
    # 4) Funzioni di Allocazione Flusso
    # ------------------------------------------------
    def allocate_flow(self, src_mac, dst_mac, bandwidth):
        """
        Tenta di allocare un flusso end-to-end con banda = bandwidth
        usando path_finder (residua se vuoi).
        """
        self.logger.info(f"Allocating flow src={src_mac}, dst={dst_mac}, bw={bandwidth}")

        if src_mac not in self.hosts or dst_mac not in self.hosts:
            self.logger.error("Host not known. Impossibile allocare flusso.")
            return False

        src_sw = self.hosts[src_mac]["dpid"]
        dst_sw = self.hosts[dst_mac]["dpid"]

        # Aggiorna la topologia
        self._get_topology_data()

        # Calcola percorso con path_finder
        path, available_bw = self.path_finder.find_max_bandwidth_path(
            src_sw, dst_sw, bandwidth
        )
        if not path:
            self.logger.error("No path found with sufficient bandwidth.")
            return False

        # Verifica banda su ogni link
        for i in range(len(path)-1):
            k_fwd = (path[i], path[i+1])
            k_rev = (path[i+1], path[i])
            if self.links[k_fwd]["residual_bw"] < bandwidth or \
               self.links[k_rev]["residual_bw"] < bandwidth:
                self.logger.error(f"Link {k_fwd} or {k_rev} insufficient bandwidth.")
                return False

        # Se ok, installa flussi e aggiorna residuo
        self.install_path_flows(path, src_mac, dst_mac)
        for i in range(len(path)-1):
            k_fwd = (path[i], path[i+1])
            k_rev = (path[i+1], path[i])
            self.links[k_fwd]["residual_bw"] -= bandwidth
            self.links[k_rev]["residual_bw"] -= bandwidth

        self.logger.info(f"Flusso allocato da {src_mac} a {dst_mac}")
        return True

    def install_path_flows(self, path, mac_src, mac_dst):
        """
        Installa flussi su ogni switch nel path, e crea regole forward & reverse
        basate su match (eth_src, eth_dst).
        """
        for i in range(len(path)-1):
            src_sw = path[i]
            dst_sw = path[i+1]

            dp_src = self.datapaths[src_sw]
            parser = dp_src.ofproto_parser
            out_port = self.get_port_between_switches(src_sw, dst_sw)

            match = parser.OFPMatch(eth_src=mac_src, eth_dst=mac_dst)
            actions = [parser.OFPActionOutput(out_port)]
            self.add_flow(dp_src, 1, match, actions)

            # Reverse
            dp_dst = self.datapaths[dst_sw]
            parser_dst = dp_dst.ofproto_parser
            back_port = self.get_port_between_switches(dst_sw, src_sw)
            match_back = parser_dst.OFPMatch(eth_src=mac_dst, eth_dst=mac_src)
            actions_back = [parser_dst.OFPActionOutput(back_port)]
            self.add_flow(dp_dst, 1, match_back, actions_back)

    # ------------------------------------------------
    # 5) Misurare banda con iPerf (flusso di misurazione dedicato)
    # ------------------------------------------------
    def measure_flow(self, mac_src, mac_dst, udp_port=5001):
        """
        1) Controlla se abbiamo IP degli host, altrimenti generiamo ARP o ping
        2) Installa flow di misurazione su tutti gli switch (oppure sul path)
        3) L'utente lancia iPerf -u da host src->dst
        4) Rimuove flow dopo tot tempo
        """
        if mac_src not in self.hosts or mac_dst not in self.hosts:
            self.logger.error(f"Hosts {mac_src}, {mac_dst} non noti.")
            return

        ip_src = self.hosts[mac_src].get("ip", None)
        ip_dst = self.hosts[mac_dst].get("ip", None)
        if not ip_src or not ip_dst:
            self.logger.warning("Non conosco ancora IP degli host. Genera ARP/ping per imparare!")
            # Se vuoi forzare l'apprendimento, puoi inviare pacchetti fittizi
            # trigger_packet_in(...) con ARP/EtherType, etc.
            return

        # Installa regole su TUTTI gli switch (o solo su path)
        for dpid, dp in self.datapaths.items():
            self._install_measurement_flow(dp, ip_src, ip_dst, udp_port)
            self._install_measurement_flow(dp, ip_dst, ip_src, udp_port)

        self.logger.info(
            f"Flow di misurazione installato. Ora esegui iperf -u da {ip_src} a {ip_dst} (porta {udp_port})."
        )
        # Rimuoverai i flow dopo tot secondi o via comando

    def _install_measurement_flow(self, dp, ip_src, ip_dst, udp_port=5001, priority=100):
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        match = parser.OFPMatch(
            eth_type=0x0800,  # IPv4
            ip_proto=17,      # UDP
            ipv4_src=ip_src,
            ipv4_dst=ip_dst
            # Se vuoi anche match su udp_src o udp_dst
            # udp_dst=udp_port
        )
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        self.add_flow(dp, priority, match, actions)
        self.logger.debug(
            f"Install measurement flow on dpid={dp.id} for IP {ip_src}->{ip_dst} UDP"
        )

    def remove_measurement_flow(self, mac_src, mac_dst, udp_port=5001):
        """
        Rimuove le regole di misurazione su tutti gli switch
        """
        if mac_src not in self.hosts or mac_dst not in self.hosts:
            return

        ip_src = self.hosts[mac_src].get("ip", None)
        ip_dst = self.hosts[mac_dst].get("ip", None)
        if not ip_src or not ip_dst:
            return

        for dpid, dp in self.datapaths.items():
            self._remove_measurement_flow(dp, ip_src, ip_dst, udp_port)
            self._remove_measurement_flow(dp, ip_dst, ip_src, udp_port)

    def _remove_measurement_flow(self, dp, ip_src, ip_dst, udp_port=5001, priority=100):
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        match = parser.OFPMatch(
            eth_type=0x0800,
            ip_proto=17,
            ipv4_src=ip_src,
            ipv4_dst=ip_dst
        )
        mod = parser.OFPFlowMod(
            datapath=dp,
            priority=priority,
            match=match,
            command=ofproto.OFPFC_DELETE_STRICT,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY
        )
        dp.send_msg(mod)
        self.logger.debug(
            f"Removed measurement flow on dpid={dp.id} for IP {ip_src}->{ip_dst}"
        )
