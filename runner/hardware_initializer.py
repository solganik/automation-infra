import json
import time

# cluster = {"host1": {"ram": 10, "host_type": "virtual"},
#            "host2" : {"gpu": (1,), "gpu_type": "1080Ti"}}
from munch import Munch

from infra.model.base_config import BaseConfig, DefaultFactoryMunch
from infra.model.host import Host

hardware_types = {
    "aio":
        {"ori":
             """{
                "ip": "192.168.20.34",
                "user": "user",
                "password": "pass",
                "key_file_path": "",
                "alias": "monster",
                "host_id": 123,
                "host_type": "physical",
                "allocation_id": "" }
             """,
         "guy":
             """{
                    "ip": "35.199.172.249",
                    "user": "anyvision-devops",
                    "password": "",
                    "key_file_path": "/home/ori/Downloads/anyvision-devops.pem",
                    "alias": "gcloud",
                    "host_id": 123,
                    "host_type": "cloud",
                    "allocation_id": ""
                }
             """
         }
}


def init_hardware(hardware_req):
    print("initilizing hardware...")
    # TODO: here I would turn to a server admin service and get ips, userPass/sshKeys of the cluster
    # This is pseudo from the
    # base_config = servers_manager.set_up(cluster)
    # TODO: but in addition to the cluster details, dont I also need to request services, like memsql, pipeng..?
    # For now, this place holder:
    time.sleep(1)
    hardware = hardware_types[hardware_req["type"]]['guy']
    print("successfully initialized hardware!")
    print()
    # TODO: Here I really need to run dev-ops tests which check that all hardware is working, no?
    # because the server_admin_service just gave me blank servers.

    return hardware