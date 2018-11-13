# VNF Deploy Package

Deploys a VNF to an NFVO infrastructure (Openstack, ESC, NSO, NFVO), sending a REST callback when the VNF is ready. 
Required IPv4 subnets are dynamically allocated using a resource-manager. 


## Dependencies

NSO packages required:
- Cisco resource-manager 
- Cisco tailf-etsi-rel2-nfvo

Python packages required:
- requests
- jinja2





