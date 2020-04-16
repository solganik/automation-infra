from aiohttp import web
import logging
# web.View

# from aiohttp import web


class HyperVisor(object):

    def __init__(self, allocator, image_store, webapp):
        self.allocator = allocator
        self.image_store = image_store
        webapp.router.add_routes([web.post('/vms', self.handle_allocate_vm),
                                  web.delete('/vms/{name}', self.handle_destroy_vm),
                                  web.get('/vms', self.handle_list_vms),
                                  web.get('/images', self.handle_list_images),
                                  web.post('/vms/{name}/status', self.handle_vm_update),
                                  web.get('/vms/{name}', self.handle_vm_status)])

    async def handle_allocate_vm(self, request):
        data = await request.json()

        networks = data['networks']
        num_cpus = int(data.get('num_cpus', 1))
        num_gpus = int(data.get('num_gpus', 0))
        base_image = data['base_image']
        base_image_size = data.get('base_image_size', None)
        memory_gb = int(data['ram'])
        disks = data['disks']
        try:
            vm = await self.allocator.allocate_vm(base_image=base_image,
                                       base_image_size=base_image_size,
                                       memory_gb=memory_gb,
                                       networks=networks,
                                       num_gpus=num_gpus,
                                       num_cpus=num_cpus,
                                       disks=disks)
        except:
            logging.exception("Failed to create VM")
            return web.json_response({'status' : 'Failed'}, status=500)
        else:
            return web.json_response({'status' : 'Success', 'name': vm.name, 'info' : vm.json}, status=200)

    async def handle_destroy_vm(self, request):
        vm_name = request.match_info['name']
        try:
            await self.allocator.destroy_vm(vm_name)
        except KeyError:
            return web.json_response(status=404)
        except:
            logging.exception("Failed to destroy VM")
            return web.json_response({'status' : 'Failed'}, status=500)
        else:
            return web.json_response({'status' : 'Success'}, status=200)

    async def handle_list_vms(self, _):
        vms_info = [vm.json for vm in self.allocator.vms.values()]
        result = []
        for vm_info in vms_info:
            vm = self.allocator.vms.get(vm_info['name'])
            if vm is None:
                continue
            status = await self.allocator.vm_manager.vm_status(vm)
            vm_info.update({"status" : status})
            result.append(vm_info)

        return web.json_response({'vms' : result}, status=200)

    async def handle_list_images(self, _):
        images = await self.image_store.list_images()
        return web.json_response({'images' : images}, status=200)

    async def handle_vm_update(self, request):
        vm_name = request.match_info['name']
        data = await request.json()
        logging.info("Asked to change vm %s status to %s", vm_name, data)
        vm = self.allocator.vms.get(vm_name)
        if vm is None:
            return web.json_response(status=404)

        power_status = data['power']

        async with vm.lock:
            # double check after lock
            if vm_name not in self.allocator.vms:
                return web.json_response(status=404)
            if power_status == "on":
                await self.allocator.vm_manager.start_vm(vm)
            elif power_status == "off":
                await self.allocator.vm_manager.stop_vm(vm)
        return web.json_response({'status' : 'Success'}, status=200)

    async def handle_vm_status(self, request):
        vm_name = request.match_info['name']
        logging.debug("Requested vm info for vm %s", vm_name)
        vm = self.allocator.vms.get(vm_name)
        if vm is None:
            return web.json_response(status=404)
        async with vm.lock:
            # double check after lock
            if vm_name not in self.allocator.vms:
                return web.json_response(status=404)
            info = await self.allocator.vm_manager.info(vm)
        return web.json_response({'info' : info}, status=200)
