from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from webob import Response

class FlowRequestHandler(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(FlowRequestHandler, self).__init__(req, link, data, **config)
        self.flow_allocator = data['flow_allocator']

    @route('flow', '/allocate_flow', methods=['POST'])
    def allocate_flow(self, req, **kwargs):
        data = req.json if req.body else {}
        src = data.get('src')
        dst = data.get('dst')
        bandwidth = data.get('bandwidth')

        if self.flow_allocator.allocate_flow(src, dst, bandwidth):
            return Response(status=200, json_body={'status': 'success'})
        return Response(status=400, json_body={'status': 'error', 'reason': 'Insufficient capacity'})




    @route('flow', '/delete_flow', methods=['DELETE'])
    def delete_flow(self, req, **kwargs):
        data = req.json if req.body else {}
        src = data.get('src')
        dst = data.get('dst')

        if self.flow_allocator.delete_flow(src, dst):
            return Response(status=200, json_body={'status': 'success'})
        return Response(status=400, json_body={'status': 'error', 'reason': 'Flow not found'})