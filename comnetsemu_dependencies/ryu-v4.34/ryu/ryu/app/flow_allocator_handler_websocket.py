import asyncio
import json
import websockets

class FlowWebSocketHandler:
    def __init__(self, flow_allocator, host="0.0.0.0", port=8765, logger=None):
        """
        Inizializza l'handler WebSocket.
        Args:
            flow_allocator: Istanza del controller (FlowAllocator) che contiene la logica di business.
            host (str): Indirizzo su cui avviare il server WebSocket.
            port (int): Porta su cui avviare il server WebSocket.
            logger: (Opzionale) logger da usare per le stampe di log.
        """
        self.flow_allocator = flow_allocator
        self.host = host
        self.port = port
        if logger is None:
            import logging
            self.logger = logging.getLogger(__name__)
        else:
            self.logger = logger

    async def handler(self, websocket, path):
        self.logger.info("Nuovo client WebSocket connesso")
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except Exception:
                    error_response = {"status": "error", "reason": "Invalid JSON"}
                    await websocket.send(json.dumps(error_response))
                    continue

                command = data.get("command", "").lower()
                if command == "allocate_flow":
                    # ... logica già esistente
                    src = data.get("src")
                    dst = data.get("dst")
                    bandwidth = data.get("bandwidth")
                    self.logger.info(f"Ricevuto allocate_flow: src={src}, dst={dst}, bandwidth={bandwidth}")
                    if self.flow_allocator.allocate_flow(src, dst, bandwidth):
                        response = {"status": "success", "command": "allocate_flow"}
                    else:
                        response = {"status": "error", "reason": "Insufficient capacity", "command": "allocate_flow"}
                elif command == "delete_flow":
                    # ... logica già esistente
                    src = data.get("src")
                    dst = data.get("dst")
                    self.logger.info(f"Ricevuto delete_flow: src={src}, dst={dst}")
                    if self.flow_allocator.delete_flow(src, dst):
                        response = {"status": "success", "command": "delete_flow"}
                    else:
                        response = {"status": "error", "reason": "Flow not found", "command": "delete_flow"}
                elif command == "dump_flows":
                    # Esempio: esegui dump-flows su uno switch
                    switch = data.get("switch")
                    try:
                        import subprocess
                        dump = subprocess.check_output(["sudo", "ovs-ofctl", "-O", "OpenFlow13", "dump-flows", switch])
                        response = {"status": "success", "command": "dump_flows", "result": dump.decode("utf-8")}
                    except Exception as e:
                        response = {"status": "error", "reason": str(e), "command": "dump_flows"}
                elif command == "ping":
                    # Esempio: esegui un ping tra due host
                    src = data.get("src")
                    dst = data.get("dst")
                    try:
                        import subprocess
                        # Esegui un ping (modifica il comando in base alle tue necessità)
                        ping_result = subprocess.check_output(["ping", "-c", "4", dst])
                        response = {"status": "success", "command": "ping", "result": ping_result.decode("utf-8")}
                    except Exception as e:
                        response = {"status": "error", "reason": str(e), "command": "ping"}
                else:
                    response = {"status": "error", "reason": "Unknown command"}
                await websocket.send(json.dumps(response))
        except websockets.ConnectionClosed:
            self.logger.info("Client WebSocket disconnesso")
        except Exception as e:
            self.logger.error(f"Errore in handler WebSocket: {e}")

    
    def start(self):
        """
        Avvia il server WebSocket in un event loop separato.
        """
        self.logger.info(f"Avvio WebSocket server su {self.host}:{self.port}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        start_server = websockets.serve(self.handler, self.host, self.port)
        loop.run_until_complete(start_server)
        loop.run_forever()
