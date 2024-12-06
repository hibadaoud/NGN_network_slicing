- To ssh to the VM: (password: vagrant)
  ```
    ssh -X -p 2222 vagrant@localhost
  ```
- The file **topology.py** defines the topology network presented in the project pdf.

To run the topology in mininet:
  ```
    sudo mn --custom topology.py --topo mytopo --controller=remote,ip=127.0.0.1,port=6653
  ```

- The file **allocator_flow.py** has the logic of the controller. To run it:
  ```
  cd /home/vagrant/comnetsemu_dependencies/ryu-v4.34/ryu/ryu/app
  ryu-manager --ofp-tcp-listen-port 6653 flow_allocater_controller.py
  ```

- The file **flow_allocator_handler_REST.py** provides a REST API interface for interacting with the Ryu controller managing network flows in it. 
To request the allocation of the flow between the hosts we call the POST method defined in this file and it will trigger the controller.
  ```
   curl -X POST -H "Content-Type: application/json" -d '{"src": "a6:0c:58:e9:86:2d", "dst": "e2:8d:18:27:c8:87", "bandwidth": 8}' http://127.0.0.1:8080/allocate_flow
  ```

-The file **path_finder.py** defines a class that determines the path between the hosts that meets the specified bandwidth.

**Steps to run the project and see what it does:**

  1/ In one terminal you ssh to the VM and run :
          ```
          sudo mn --custom topology.py --topo mytopo --controller=remote,ip=127.0.0.1,port=6653
          ```
  
  2/ In onther terminal you ssh to the VM and run : 
          ```
          cd /home/vagrant/comnetsemu_dependencies/ryu-v4.34/ryu/ryu/app
          ryu-manager --ofp-tcp-listen-port 6653 flow_allocater_controller.py
          ```
  3/ In onther terminal you ssh to the VM and run: (change the src_mac and dest_mac with the ones specified in the mininet cli) :
         ```
         curl -X POST -H "Content-Type: application/json" -d '{"src": "a6:0c:58:e9:86:2d", "dst": "e2:8d:18:27:c8:87", "bandwidth": 8}' http://127.0.0.1:8080/allocate_flow
         ```
  
