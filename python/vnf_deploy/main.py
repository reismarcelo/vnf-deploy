# -*- mode: python; python-indent: 4 -*-
import ncs
from ncs.application import Service
from ncs.dp import Action
from _ncs import decrypt
import requests
import jinja2
from ipaddress import ip_network
from tailf_etsi_rel2_nfvo_esc import helpers as nfvo_helpers
from vnf_deploy.utils import apply_template, BatchAllocator, Allocation, plan_data_service


class ServiceCallbacks(Service):
    @Service.create
    @plan_data_service('vnf-deploy:resource-allocations', 'vnf-deploy:vnf-ready')
    def cb_create(self, tctx, root, service, proplist, self_plan):

        # Setup kickers
        tpl_vars = {
            'DEPLOYMENT_NAME': 'vnf-deploy-{}'.format(service.name),
        }
        # TODO: kickers template can probably be improved
        apply_template('vnf-deploy-kickers', service, tpl_vars)

        # Perform subnet allocations
        common_cfg = root.ncs__services.vnf_deploy__vnf_deploy.common
        allocator = BatchAllocator(tctx.username, root, service)
        allocator.append(Allocation.type.address,
                         common_cfg.mgmt_intf.pool_name,
                         Allocation.get_id('mgmt', service.name),
                         length=common_cfg.mgmt_intf.prefix_length)
        allocator.append(Allocation.type.address,
                         common_cfg.inet_intf.pool_name,
                         Allocation.get_id('inet', service.name),
                         length=common_cfg.inet_intf.prefix_length)

        allocations = allocator.read()
        if allocations is None:
            self.log.info('Resource allocations are not ready')
            return

        allocations_iter = iter(allocations)
        mgmt_subnet = next(allocations_iter)
        inet_subnet = next(allocations_iter)

        self_plan.set_reached('vnf-deploy:resource-allocations')

        # Launch VNF
        vnf_vars = {
            **tpl_vars,
            'MGMT_ADDR': subnet_first_host(mgmt_subnet),
            'INET_ADDR': subnet_first_host(inet_subnet),
        }
        apply_template('nfvo-vnf-info', service, vnf_vars)

        if not nfvo_helpers.is_vnf_ready(tctx, service.tenant, tpl_vars['DEPLOYMENT_NAME'], service.esc):
            self.log.info('Deployment not yet ready')
            return

        self_plan.set_reached('vnf-deploy:vnf-ready')

        return proplist


class ActionCallbacks(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output):
        self.log.info("Action {}".format(kp))

        with ncs.maapi.single_read_trans(uinfo.username, "system") as read_t:
            root = ncs.maagic.get_root(read_t)

            rest_params = root.ncs__services.vnf_deploy__vnf_deploy.rest_callback
            uri = rest_params.uri
            source_data = rest_params.payload
            rest_user = rest_params.username
            read_t.maapi.install_crypto_keys()
            rest_pass = decrypt(rest_params.password)

            # kp example: /ncs:services/vnf-deploy:vnf-deploy/vnf{csr-123}
            kp_node = ncs.maagic.cd(root, kp)
            data_vars = {
                'vnf_name': kp_node.name,
            }

        # Process source_data through Jinja2
        jinja_env = jinja2.Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
        data = jinja_env.from_string(source_data).render(data_vars)

        # Send REST notification
        try:
            response = requests.post(url=uri, auth=(rest_user, rest_pass), data=data)
            response.raise_for_status()
            self.log.info("REST notification sent successfully: status code {}.".format(response.status_code))
        except requests.exceptions.RequestException as e:
            self.log.error("REST notification failed: {}".format(e))


def subnet_first_host(subnet_str):
    """
    Return the first valid IP address in the subnet
    :param subnet_str: IP subnet as a string in <prefix>/<len> format
    :return: String representing the IP address in <prefix>/<len> format
    """
    subnet = ip_network(subnet_str)
    return '{}/{}'.format(next(subnet.hosts()), subnet.prefixlen)


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):
        self.log.info('Main RUNNING')

        # Registration of service callbacks
        self.register_service('vnf-deploy-servicepoint', ServiceCallbacks)

        # Registration of action callbacks
        self.register_action('vnf-deploy-actionpoint', ActionCallbacks)

    def teardown(self):
        self.log.info('Main FINISHED')
