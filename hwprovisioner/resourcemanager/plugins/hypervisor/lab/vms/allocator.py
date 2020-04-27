import logging
from lab import NotEnoughResourceException
from . import vm
import asyncio
import copy


class VMRestoreException(Exception):

    def __init__(self, vm_data, reason):
        msg = f"Failed to restore vm {vm_data} reason: {reason}"
        super().__init__(msg)


class Allocator(object):

    def __init__(self, mac_addresses, gpus_list, vm_manager, server_name, max_vms,
                 sol_base_port, paravirt_device, private_network="default"):
        self.mac_addresses = mac_addresses
        self.gpus_list = gpus_list
        self.vms = {}
        self.vm_manager = vm_manager
        self.server_name = server_name
        self.max_vms = max_vms
        self.paravirt_net_device = paravirt_device
        self.private_network = private_network
        self.sol_base_port = sol_base_port

    async def _try_restore_ip(self, vm_data, net_iface, max_retries):
        last_error = None
        for i in range(max_retries):
            try:
                await self.vm_manager.dhcp_manager.reallocate_ip(net_iface)
                break
            except TimeoutError as e:
                logging.warning(f"try {i} Ip reallocation failed on machine {vm_data} machine might not be accessibe")
                last_error = e
        else:
            raise last_error

    async def _try_restore_vm(self, vm_data):
        pcis_info = vm_data.get('pcis', [])
        macs_to_reserve = []
        gpus_to_reserve = []
        # This is dirty hack, since xml is missing the "disks" and we need this variable to
        # exists empty in order to correctly restore vm we initialize it here
        vm_data.setdefault('disks', [])
        # First check if storage is valid
        if not await self.vm_manager.verify_storage_valid(vm_data):
            raise VMRestoreException(vm_data, "Storage is not valid")

        vm_nets = vm_data.get('net_ifaces', None)
        for net_iface in vm_nets:
            # check if net device is still valid, i.e. was not changed
            if net_iface['source'] not in [self.paravirt_net_device, self.private_network]:
                raise Exception("Network device %s for vm %s no longer exists", net_iface, vm_data)
            if net_iface['macaddress'] not in self.mac_addresses:
                raise VMRestoreException(vm_data, "Mac address %s for is no longer available pool %s",
                                net_iface['macaddress'], self.mac_addresses)
            macs_to_reserve.append(net_iface['macaddress'])

            # Now lets try to reserve the ip VM previously had
            try:
                await self._try_restore_ip(vm_data, net_iface, max_retries=10)
            except TimeoutError:
                logging.error(f"Ip reallocation failed on machine {vm_data} machine might not be accessibe" , exc_info=True)
            except Exception as e:
                raise VMRestoreException(vm_data, f'Failed to init networks of vm {vm_data}') from e

        for pci in pcis_info:
            matchind_gpu = [gpu for gpu in self.gpus_list if gpu.full_address == pci]
            if len(matchind_gpu) == 0:
                raise VMRestoreException(vm_data, "VM PCI address is not available in pci list %s", self.gpus_list)
            gpus_to_reserve.append(matchind_gpu[0])

        # We got here .. all good lets take gpu and mac addresses from the list
        vm_data['pcis'] = gpus_to_reserve
        # Lets take mac addresses from the list
        for mac in macs_to_reserve:
            self.mac_addresses.remove(mac)
        machine = vm.VM(**vm_data)
        self.vms[machine.name] = machine
        logging.info("Restored vm %s", machine)

    async def restore_vms(self):
        vms = await self.vm_manager.load_vms_data()
        restored = 0
        failed = 0
        for vm in vms:
            try:
                await self._try_restore_vm(vm)
                restored = restored + 1
            except:
                failed = failed + 1
                logging.exception("Failed to restore vm %s .. deleting it", vm)
                await self.vm_manager.destroy_vm(vm)
        logging.info("Restored %d out of %d vms vms: %s", restored, failed, self.vms)

    async def delete_all_dangling_vms(self):
        logging.info("Deleting all leftover vm resources")
        vms_data = await self.vm_manager.load_vms_data()
        for vm_data in vms_data:
            # We dont need pci info, and we dont want to load old stored one .. so just remove it
            vm_data.pop('pci', None)
            machine = vm.VM(**vm_data)
            await self.vm_manager.destroy_vm(machine)

    def _sol_port(self):
        return self.sol_base_port + len(self.vms)

    def _reserve_gpus(self, num_gpus):
        gpus = self.gpus_list[:num_gpus]
        self.gpus_list = self.gpus_list[num_gpus:]
        return gpus

    def _reserve_macs(self, num_macs):
        required_macs = self.mac_addresses[:len(num_macs)]
        self.mac_addresses = self.mac_addresses[len(num_macs):]
        return required_macs

    def _reserve_networks(self, networks):
        required_macs = self._reserve_macs(networks)

        return [{"macaddress" : mac,
                 "mode" : network_type,
                 'source' : self.paravirt_net_device if network_type == 'bridge' else self.private_network}
                for mac, network_type in zip(required_macs, networks)]

    def _free_vm_resources(self, gpus, networks):
        macs = [net['macaddress'] for net in networks]
        self.gpus_list.extend(gpus)
        self.mac_addresses.extend(macs)

    @staticmethod
    def _validate_networks_params(networks):
        for net in networks:
            if net not in ('bridge', 'isolated'):
                raise ValueError(f"Invalid network parameter {networks}")

    async def allocate_vm(self, base_image, base_image_size, memory_gb, networks, num_gpus=0, num_cpus=4, disks=None):
        ''' 
        @networks - list of networks that we want to allocate, possible 
        values are "isolated, bridge"
        @num_gpus - number of GPU`s to allocate 
        @num_cpus - number of CPU`s to allocate
        @memory_gb - memory in GB for vm
        @disks   - dict of {"size" : X, 'type' : [ssd or hdd]} to allocate disks
        '''
        disks = disks or []
        logging.debug("Allocate vm image %(base_image)s memory %(memory_gb)s networks\
                       %(networks)s cpus %(num_cpus)s gpus %(num_gpus)s disks %(disks)s",
                      dict(base_image=base_image, memory_gb=memory_gb, num_gpus=num_gpus, num_cpus=num_cpus, networks=networks, disks=disks))

        # check that i have enough networks in pool 
        if len(networks) > len(self.mac_addresses):
            raise NotEnoughResourceException(f"Not nrough mac addresses in pool requested: {networks} has {self.mac_addresses}")
        # Check that i have enough gpus 
        if num_gpus > len(self.gpus_list):
            raise NotEnoughResourceException(f"Not enough gpus requested : {num_gpus} has {self.gpus_list}")

        Allocator._validate_networks_params(networks)

        if self.max_vms == len(self.vms):
            raise NotEnoughResourceException(f"Cannot allocate more vms currently {self.vms}")

        gpus = self._reserve_gpus(num_gpus)
        networks = self._reserve_networks(networks)
        vm_name = "%s-vm-%d" % (self.server_name, len(self.vms))
        machine = vm.VM(name=vm_name, num_cpus=num_cpus, memsize=memory_gb,
                         net_ifaces=networks, sol_port=self._sol_port(),
                         pcis=gpus, base_image=base_image,
                         disks=disks, base_image_size=base_image_size)
        self.vms[vm_name] = machine

        async with machine.lock:
            try:
                await self.vm_manager.allocate_vm(machine)
            except:
                self._free_vm_resources(gpus, networks)
                del self.vms[vm_name]
                raise
            else:
                logging.info(f"Allocated vm {vm}")
        return machine

    async def destroy_vm(self, name):
        vm = self.vms.get(name, None)
        if not vm:
            raise KeyError()
        async with vm.lock:
            # double check that vm is not yet deleted
            if not name in self.vms:
                raise KeyError()
            try:
                await self.vm_manager.destroy_vm(vm)
            except:
                logging.exception("Failed to free vm %s", vm.name)
                raise
            else:
                del self.vms[name]
                self._free_vm_resources(vm.pcis, vm.net_ifaces)