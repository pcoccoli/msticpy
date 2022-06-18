# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------
"""
ip_utils - IP Address functions.

Contains a series of functions required to manipulate and enrich IP Address data
to assist investigations.

Designed to support any data source containing IP address entity.

"""
import ipaddress
import warnings
from functools import lru_cache
from typing import List, Optional, Set, Tuple

import pandas as pd
from ipwhois import (
    ASNRegistryError,
    HostLookupError,
    HTTPLookupError,
    HTTPRateLimitError,
    IPWhois,
    WhoisLookupError,
    WhoisRateLimitError,
)

from .._version import VERSION
from ..common.utility import arg_to_list, export
from ..datamodel.entities import IpAddress

__version__ = VERSION
__author__ = "Ashwin Patil"


@export  # noqa: MC0001
def convert_to_ip_entities(  # noqa: MC0001
    ip_str: Optional[str] = None,
    data: Optional[pd.DataFrame] = None,
    ip_col: Optional[str] = None,
    geo_lookup: bool = True,
) -> List[IpAddress]:  # noqa: MC0001
    """
    Take in an IP Address string and converts it to an IP Entity.

    Parameters
    ----------
    ip_str : str
        A string with a single IP Address or multiple addresses
        delimited by comma or space
    data : pd.DataFrame
        Use DataFrame as input
    ip_col : str
        Column containing IP addresses
    geo_lookup : bool
        If true, do geolocation lookup on IPs,
        by default, True

    Returns
    -------
    List
        The populated IP entities including address and geo-location

    Raises
    ------
    ValueError
        If neither ip_string or data/column provided as input

    """
    # locally imported to prevent cyclic import
    # pylint: disable=import-outside-toplevel, cyclic-import
    from .geoip import GeoLiteLookup

    geo_lite_lookup = GeoLiteLookup()

    ip_entities: List[IpAddress] = []
    all_ips: Set[str] = set()

    if ip_str:
        addrs = arg_to_list(ip_str)
    elif data is not None and ip_col:
        addrs = data[ip_col].values
    else:
        raise ValueError("Must specify either ip_str or data + ip_col parameters.")

    for addr in addrs:
        if isinstance(addr, list):
            ip_list = set(addr)
        elif isinstance(addr, str) and "," in addr:
            ip_list = {ip.strip() for ip in addr.split(",")}
        else:
            ip_list = {addr}
        ip_list = ip_list - all_ips  # remove IP addresses we've seen
        ip_entities.extend(IpAddress(Address=ip) for ip in ip_list)
        all_ips |= ip_list
        if geo_lookup:
            for ip_ent in ip_entities:
                geo_lite_lookup.lookup_ip(ip_entity=ip_ent)
    return ip_entities


@export  # noqa: MC0001
# pylint: disable=too-many-return-statements, invalid-name
def get_ip_type(ip: str = None, ip_str: str = None) -> str:  # noqa: MC0001
    """
    Validate value is an IP address and determine IPType category.

    (IPAddress category is e.g. Private/Public/Multicast).

    Parameters
    ----------
    ip : str
        The string of the IP Address
    ip_str : str
        The string of the IP Address - alias for `ip`

    Returns
    -------
    str
        Returns ip type string using ip address module

    """
    ip_str = ip or ip_str
    if not ip_str:
        raise ValueError("'ip' or 'ip_str' value must be specified")
    try:
        ipaddress.ip_address(ip_str)
    except ValueError:
        print(f"{ip_str} does not appear to be an IPv4 or IPv6 address")
    else:
        if ipaddress.ip_address(ip_str).is_multicast:
            return "Multicast"
        if ipaddress.ip_address(ip_str).is_global:
            return "Public"
        if ipaddress.ip_address(ip_str).is_loopback:
            return "Loopback"
        if ipaddress.ip_address(ip_str).is_link_local:
            return "Link Local"
        if ipaddress.ip_address(ip_str).is_unspecified:
            return "Unspecified"
        if ipaddress.ip_address(ip_str).is_private:
            return "Private"
        if ipaddress.ip_address(ip_str).is_reserved:
            return "Reserved"

    return "Unspecified"


# pylint: enable=too-many-return-statements


# pylint: disable=invalid-name
@export
@lru_cache(maxsize=1024)
def get_whois_info(
    ip: str = None, show_progress: bool = False, **kwargs
) -> Tuple[str, dict]:
    """
    Retrieve whois ASN information for given IP address using IPWhois python package.

    Parameters
    ----------
    ip : str
        IP Address to look up.
    ip_str : str
        alias for `ip`.
    show_progress : bool, optional
        Show progress for each query, by default False

    Returns
    -------
    IP
        Details of the IP data collected

    Notes
    -----
    This function uses the Python functools lru_cache and
    will return answers from the cache for previously queried
    IP addresses.

    """
    ip_str = ip or kwargs.get("ip_str")
    if not ip_str:
        raise ValueError("'ip' or 'ip_str' value must be specified")
    ip_type = get_ip_type(ip_str)
    if ip_type == "Public":
        try:
            whois = IPWhois(ip_str)
            whois_result = whois.lookup_whois()
            if show_progress:
                print(".", end="")
            return whois_result["asn_description"], whois_result
        except (
            HTTPLookupError,
            HTTPRateLimitError,
            HostLookupError,
            WhoisLookupError,
            WhoisRateLimitError,
            ASNRegistryError,
        ) as err:
            return f"Error during lookup of {ip_str} {type(err)}", {}
    return f"No ASN Information for IP type: {ip_type}", {}


# pylint: enable=invalid-name


@export
def get_whois_df(
    data: pd.DataFrame,
    ip_column: str,
    all_columns: bool = False,
    asn_col: str = "AsnDescription",
    whois_col: Optional[str] = None,
    show_progress: bool = False,
) -> pd.DataFrame:
    """
    Retrieve Whois ASN information for DataFrame of IP Addresses.

    Parameters
    ----------
    data : pd.DataFrame
        Input DataFrame
    ip_column : str
        Column name of IP Address to look up.
    all_columns:
        Expand all whois data to columns.
    asn_col : str, optional
        Name of the output column for ASN description,
        by default "ASNDescription".
        Ignored if `all_columns` is True.
    whois_col : str, optional
        Name of the output column for full whois data,
        by default "WhoIsData"
        Ignored if `all_columns` is True.
    show_progress : bool, optional
        Show progress for each query, by default False

    Returns
    -------
    pd.DataFrame
        Output DataFrame with results in added columns.

    """
    if all_columns:
        return data.apply(
            lambda x: get_whois_info(x[ip_column], show_progress=show_progress)[1],
            axis=1,
            result_type="expand",
        )
    data = data.copy()
    if whois_col is not None:
        data[[asn_col, whois_col]] = data.apply(
            lambda x: get_whois_info(x[ip_column], show_progress=show_progress),
            axis=1,
            result_type="expand",
        )
    else:
        data[asn_col] = data.apply(
            lambda x: get_whois_info(x[ip_column], show_progress=show_progress)[0],
            axis=1,
        )
    return data


@pd.api.extensions.register_dataframe_accessor("mp_whois")
@export
class IpWhoisAccessor:
    """Pandas api extension for IP Whois lookup."""

    def __init__(self, pandas_obj):
        """Instantiate pandas extension class."""
        self._df = pandas_obj

    def lookup(self, ip_column, **kwargs):
        """
        Extract IoCs from either a pandas DataFrame.

        Parameters
        ----------
        ip_column : str
            Column name of IP Address to look up.

        Other Parameters
        ----------------
        asn_col : str, optional
            Name of the output column for ASN description,
            by default "ASNDescription"
        whois_col : str, optional
            Name of the output column for full whois data,
            by default "WhoIsData"
        show_progress : bool, optional
            Show progress for each query, by default False

        Returns
        -------
        pd.DataFrame
            Output DataFrame with results in added columns.

        """
        warn_message = (
            "This accessor method has been deprecated.\n"
            "Please use IpAddress.util.whois() pivot function."
            "This will be removed in MSTICPy v2.2.0"
        )
        warnings.warn(warn_message, category=DeprecationWarning)
        return get_whois_df(data=self._df, ip_column=ip_column, **kwargs)