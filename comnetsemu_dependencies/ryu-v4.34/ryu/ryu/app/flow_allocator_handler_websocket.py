import asyncio
import json
import websockets


class FlowWebSocketHandler:
    def __init__(self, flow_allocator, host="0.0.0.0", port=8765, logger=None):
        """
        Initialize the WebSocket handler.
        Args:
            flow_allocator: Instance of the controller (FlowAllocator) that contains business logic.
            host (str): Address to start the WebSocket server on.
            port (int): Port to start the WebSocket server on. 
            logger: (Optional) logger to use for log messages.
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
        self.logger.info("New WebSocket client connected")

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
                    src = data.get("src")
                    dst = data.get("dst")
                    bandwidth = data.get("bandwidth")
                    self.logger.info(f"Recieved allocate_flow: src={src}, dst={dst}, bandwidth={bandwidth}")
                    if self.flow_allocator.allocate_flow(src, dst, bandwidth):
                        response = {"status": "success", "command": "allocate_flow"}
                    else:
                        response = {"status": "error", "reason": "Insufficient capacity", "command": "allocate_flow"}
                elif command == "show_reservation":
                    try: 
                        reservations= self.flow_allocator.show_reservation()
                        response = {"status": "success", "command": "show_reservation", "result": reservations}
                    except Exception as e:
                        response = {"status": "error", "reason": str(e), "command": "show_reservation"}
                elif command == "delete_flow":
                    src = data.get("src")
                    dst = data.get("dst")
                    self.logger.info(f"Recieved delete_flow: src={src}, dst={dst}")
                    if self.flow_allocator.delete_flow(src, dst):
                        response = {"status": "success", "command": "delete_flow"}
                    else:
                        response = {"status": "error", "reason": "Flow not found", "command": "delete_flow"}
                elif command == "dump_flows":
                    switch = data.get("switch")
                    try:
                        import subprocess
                        dump = subprocess.check_output(["sudo", "ovs-ofctl", "-O", "OpenFlow13", "dump-flows", switch])
                        response = {"status": "success", "command": "dump_flows", "result": dump.decode("utf-8")}
                    except Exception as e:
                        response = {"status": "error", "reason": str(e), "command": "dump_flows"}

                # elif command == "ping":
                #     src = data.get("src")  # Example: "h1"
                #     dst = data.get("dst")  # Example: "h2"
                #     print(f"Received ping request: {src} -> {dst}")

                #     try:
                #         import subprocess

                #          # ✅ Get the IP address of the destination host
                #         dst_pid = subprocess.check_output(f"pgrep -f 'mininet:{dst}'", shell=True).decode().strip().split("\n")[0]
                #         dst_ip_output = subprocess.check_output([
                #                 "sudo", "mnexec", "-a", dst_pid, "ip", "-4", "addr", "show", "dev", f"{dst}-eth0"
                #             ]).decode().strip()

                #         # ✅ Extract the actual IP address safely
                #         dst_ip_lines = [line for line in dst_ip_output.split("\n") if "inet " in line]
                #         if not dst_ip_lines:
                #             raise ValueError(f"Could not find IP for {dst}")

                #         dst_ip = dst_ip_lines[0].split()[1].split('/')[0]

                #         if not dst_ip:
                #             raise ValueError(f"Could not determine IP for {dst}")
                        
                #         src_pid = subprocess.check_output(f"pgrep -f 'mininet:{src}'", shell=True).decode().strip().split("\n")[0]
                    
                #         # ✅ Run the ping command using `mnexec`
                #         ping_cmd = f"sudo mnexec -a {src_pid} ping -c 1 {dst_ip}"
                #         ping_result = subprocess.check_output(ping_cmd, shell=True).decode()

                #         response = {"status": "success", "command": "ping", "result": ping_result}
                #     except subprocess.CalledProcessError:
                #         response = {"status": "error", "reason": f"Ping failed between {src} and {dst}", "command": "ping"}
                #     except Exception as e:
                #         response = {"status": "error", "reason": str(e), "command": "ping"}
                
                else:
                    response = {"status": "error", "reason": "Unknown command"}
                await websocket.send(json.dumps(response))


        except websockets.ConnectionClosed:
            self.logger.info("WebSocket client disconnected")
        except Exception as e:
            self.logger.error(f"Error in WebSocket handler: {e}")


    
    def start(self):
        """
        Start the WebSocket server in a separate event loop.
        """
        self.logger.info(f"Starting WebSocket server on {self.host}:{self.port}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        start_server = websockets.serve(self.handler, self.host, self.port)
        loop.run_until_complete(start_server)
        loop.run_forever()