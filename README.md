# NGN Newtork slicing exam

## Instruction and file description

To ssh to the VM: (password: vagrant)

```
  ssh -X -p 2222 vagrant@localhost
```

---

### Topology

The file **topology.py** defines the topology network presented in the project pdf.

To run the topology in mininet, from the root folder:

```
  sudo python3 topology.py
```

---

### Controller

The file **flow_allocator_controller.py** is the controller of the network. To run it from the root folder use the shell script:

```
sudo ./start_controller.sh
```

---

### REST Interface

The file **flow_allocator_handler_REST.py** provides a REST API interface for interacting with the Ryu controller managing network flows in it.

To request the allocation of the flow between the hosts we call the POST method defined in this file and it will trigger the controller.

#### Automatic

Run the python script that reads from a dump file from the mininet topology the generated MAC adresses of the hosts and let's you just choose the host name (eg. requests a flow from h1 to h2).

From the root folder run:

```
  sudo python3 tester.py
```

#### Manual

From a terminal run:

```
 curl -X POST -H "Content-Type: application/json" -d '{"src": "<source_host>", "dst": "<destination_host>", "bandwidth": <requested_bandwidth>}' http://127.0.0.1:8080/allocate_flow
```

Where you can specify desired src, dst and bandwidth.

---

### Path finder

The file **path_finder.py** defines a class that determines the path between the hosts that meets the specified bandwidth.

## Note:

**For each step you'll need to open a new terminal connected to the VM. So at least 3 shells.**

All set :smile:
