import asyncio
import json
import os
import websockets

# URI del server WebSocket (deve corrispondere alla configurazione del tuo handler)
WS_SERVER_URI = "ws://127.0.0.1:8765"

def get_mininet_macs():
    """
    Legge gli indirizzi MAC da un file pre-generato da Mininet.
    """
    mac_file = "/tmp/host_info.json"

    if not os.path.exists(mac_file):
        print("File degli indirizzi MAC non trovato. Assicurati che Mininet sia in esecuzione e stia generando il file.")
        return {}

    with open(mac_file, "r") as f:
        hosts_mac = json.load(f)

    print("Indirizzi MAC caricati:", hosts_mac)
    return hosts_mac

def select_hosts(hosts_mac):
    """
    Permette di selezionare host sorgente e destinazione.
    """
    print("\nSeleziona gli host per la trasmissione dei pacchetti:\n")
    host_list = list(hosts_mac.items())

    for i, (host, mac_info) in enumerate(host_list):
        print(f"{i + 1}. {host} - {mac_info}")

    try:
        src_index = int(input("\nSeleziona l'host sorgente (1,2,...): ")) - 1
        dst_index = int(input("Seleziona l'host di destinazione (1,2,...): ")) - 1

        if src_index == dst_index:
            print("Errore: l'host sorgente e quello di destinazione devono essere diversi.")
            return None, None

        src = host_list[src_index][1]
        dst = host_list[dst_index][1]
        
        return src, dst
    except (ValueError, IndexError):
        print("Selezione non valida.")
        return None, None

async def send_ws_request(data):
    """
    Invia una richiesta JSON tramite WebSocket e attende la risposta.
    """
    async with websockets.connect(WS_SERVER_URI) as websocket:
        await websocket.send(json.dumps(data))
        response = await websocket.recv()
        return json.loads(response)
    
def run_async(coro):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


def send_websocket_allocate_request(src, dst, bandwidth=8):
    """
    Invia una richiesta tramite WebSocket per allocare un flow.
    """
    data = {
        "command": "allocate_flow",
        "src": src['mac'],
        "dst": dst['mac'],
        "bandwidth": bandwidth
    }
    print(f"\nInvio richiesta WebSocket: {data}")
    response = run_async(send_ws_request(data))
    if response.get("status") == "success":
        print("Flow allocato con successo!")
    else:
        print(f"Errore nell'allocazione del flow: {response.get('reason', 'Errore sconosciuto')}")



def send_websocket_delete_request(src, dst):
    """
    Invia una richiesta tramite WebSocket per cancellare un flow.
    """
    data = {
        "command": "delete_flow",
        "src": src['mac'],
        "dst": dst['mac']
    }
    print(f"\nInvio richiesta WebSocket: {data}")
    response = run_async(send_ws_request(data))
    if response.get("status") == "success":
        print("Flow cancellato con successo!")
    else:
        print(f"Errore nella cancellazione del flow: {response.get('reason', 'Errore sconosciuto')}")



def run_cli():
    """
    Interfaccia CLI che mostra un'intro e rimane in ascolto dei comandi.
    """
    print("Benvenuto nel Flow Manager per Mininet (WebSocket)!")
    print("Comandi disponibili:")
    print("  allocate - Allocare un nuovo flow")
    print("  delete   - Cancellare un flow esistente")
    print("  exit     - Uscire")

    hosts_mac = get_mininet_macs()
    if not hosts_mac:
        print("Nessun indirizzo MAC trovato. Assicurati che Mininet sia in esecuzione.")
        return

    while True:
        command = input("\nInserisci comando (allocate, delete, exit): ").strip().lower()
        if command == "exit":
            print("Uscita...")
            break
        elif command == "allocate":
            src, dst = select_hosts(hosts_mac)
            if src and dst:
                try:
                    bandwidth = int(input("Inserisci la banda (Mbps): "))
                except ValueError:
                    print("Valore di banda non valido, verrà utilizzato il valore predefinito di 8 Mbps.")
                    bandwidth = 8
                send_websocket_allocate_request(src, dst, bandwidth)
        elif command == "delete":
            src, dst = select_hosts(hosts_mac)
            if src and dst:
                send_websocket_delete_request(src, dst)
        else:
            print("Comando sconosciuto. Riprova inserendo 'allocate', 'delete' o 'exit'.")

def main():
    run_cli()

if __name__ == "__main__":
    main()
