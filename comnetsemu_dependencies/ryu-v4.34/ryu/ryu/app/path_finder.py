import heapq

class PathFinder:
    def __init__(self, link_capacities, logger):
        """
        Initialize the PathFinder with link capacities and a logger.
        :param link_capacities: Dictionary of link capacities {(node1, node2): capacity}.
        :param logger: Logger from the Ryu controller.
        """
        self.graph = None
        self.link_capacities = link_capacities
        self.logger = logger
        self.build_graph()
        

    def build_graph(self):
        """
        Build a graph from link capacities.
        :return: Dictionary representing the graph structure.
        """
        graph = {}
        for (u, v), capacity in self.link_capacities.items():
            if u not in graph:
                graph[u] = {}
            graph[u][v] = capacity
        self.logger.info(f"Graph structure: {graph}")
        self.graph = graph

    def find_max_bandwidth_path(self, src, dst, required_bandwidth=0):
        """
        Finds a path with sufficient bandwidth between src and dst.

        :param src: Source node (switch ID).
        :param dst: Destination node (switch ID).
        :param required_bandwidth: The required bandwidth for the path.
        :return: Tuple (path, bandwidth), or (None, 0) if no path exists.
        """
        self.logger.info(f"Finding path: src={src}, dst={dst}, required_bandwidth={required_bandwidth}")

        # Use src["dpid"] and dst["dpid"] as identifiers
        src_dpid = src['dpid']
        dst_dpid = dst['dpid']

        # Priority queue for maximum bandwidth path search
        pq = [(-float('inf'), src_dpid, [])]  # (-bandwidth, current_node, path)
        
        # print all pq values
        self.logger.info(f"pq: {pq}")
        
        visited = set()

        while pq:
            bandwidth, node, path = heapq.heappop(pq)
            bandwidth = -bandwidth  # Convert back to positive bandwidth
            self.logger.info(f"Visiting node: {node}, path: {path}, bandwidth: {bandwidth}")

            if node in visited:
                continue
            visited.add(node)
            
            self.logger.info(f"Visited nodes: {visited}")

            # If destination is reached, return the path and bottleneck bandwidth
            if node == dst_dpid:
                self.logger.info(f"Destination reached: {node}")
                if bandwidth >= required_bandwidth:
                    self.logger.info(f"Path found: {path + [dst_dpid]}, bandwidth: {bandwidth}")
                    return path + [dst_dpid], bandwidth

            self.logger.info(f"Neighbors: {self.graph.get(node, {})}")
            # Evaluate neighbors
            for neighbor, capacity in self.graph.get(node, {}).items():
                self.logger.info(f"Neighbor: {neighbor}, capacity: {capacity}")
                if neighbor not in visited:
                    new_bandwidth = min(bandwidth, capacity) if bandwidth != float('inf') else capacity
                    if new_bandwidth >= required_bandwidth:  # Only consider valid links
                        self.logger.info(f"Evaluating link: {node} -> {neighbor}, capacity: {capacity}, new_bandwidth: {new_bandwidth}")
                        heapq.heappush(pq, (-new_bandwidth, neighbor, path + [node]))

        self.logger.error("No path found.")
        return None, 0