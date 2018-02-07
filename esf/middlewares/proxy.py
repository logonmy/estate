import random
import logging
import urllib
import requests
from bs4 import BeautifulSoup
import time
from stem import Signal
from stem.control import Controller

from scrapy.utils.project import get_project_settings
from  twisted.internet.error import TimeoutError


class TorProxyMiddleware(object):
    def __init__(self):
        self._import_setting()
        self.ip = self.get_ip()
        self.req_counter = 0

    def get_ip(self):
        url = "http://icanhazip.com"
        return requests.get(url,proxies=self.requests_proxy).text.strip()

    def _import_setting(self):
        settings = get_project_settings()
        self.http_proxy = settings["HTTP_PROXY"]
        self.tor_password = settings["PASSWORD"]
        self.control_port = settings["CONTROL_PORT"]
        self.max_req_per_ip = settings["MAX_REQ_PER_IP"]
        self.requests_proxy = { "http": self.http_proxy,
                                "https": self.http_proxy}
        # nodes that singal to exits tor
        self.exit_nodes = settings["EXIT_NODES"]
        if self.exit_nodes:
            with Controller.from_port(port=self.control_port) as controller:
                controller.authenticate()
                controller.set_conf('ExitNodes',self.exit_nodes)

    def change_ip(self):
        with Controller.from_port(port=self.control_port) as controller:
            controller.authenticate()
            controller.signal(Signal.NEWNYM)
        return self.get_ip()

    def process_request(self, request, spider):
        self.req_counter += 1
        if self.max_req_per_ip is not None and self.req_counter > self.max_req_per_ip:
            i = 1
            while 1:
                ip = self.change_ip()
                i += 1
                if ip != self.ip or i > 10:
                    self.ip = ip
                    break
        request.meta['proxy'] = self.http_proxy
        logging.info("Using proxy: %s" % request.meta["proxy"])


class HTTPProxyMiddleware(object):
    proxies = []
    max_proxies = 10000

    # for proxy
    start_page = 1
    end_page = 10

    headers = {
        "User-Agent":get_project_settings()["USER_AGENT"]
    }

    def __init__(self):
        self.time = time.time()
        self.loger = logging.getLogger(__file__)
        self.query_proxies()

    def query_proxies(self):
        api = "http://dev.kuaidaili.com/api/getproxy/?orderid=981755959684297&num=100&port=8080&b_pcchrome=1&b_pcie=1&b_pcff=1&protocol=1&method=1&an_an=1&an_ha=1&sp1=1&sep=1"
        urls = [ 'http://%s' %ip for ip in requests.get(api,headers=self.headers).text.split()]
        # urls = [i.strip() for i in open("proxies.txt").readlines()]
        for url in urls:
            # req = requests.get(url,headers = self.headers)
            # if req.status_code == 200:

                # bs = BeautifulSoup(req.text, 'html.parser')
            #     for tr in bs.findAll("tr"):
            #         cells = tr.findAll("td")
            #         if len(cells) == 7:
            #             proxy = cells[3].text + "://" + cells[0].text+ ":" + cells[1].text
            #             self.proxies.append(proxy)
            #             logging.info("add proxy: %s" % proxy)
            # req.close()
            if url not in self.proxies:
                self.proxies.append(url)
                self.loger.info("add proxy: %s" %url)
        # self.start_page = self.end_page
        # self.end_page += 10

    def process_request(self, request, spider):
        if time.time() - self.time > 600 and time.time() - self.time > 5: # api restrict
            self.loger.info("add new proxies")
            self.time = time.time()
            self.proxies = []
            self.query_proxies()
            self.loger.info("%d proxies now " %len(self.proxies))

        if hasattr(request.meta,"proxy"):
            self.loger.info("request has proxy already, remove it")
            self.remove_failed_proxy(request,spider)

        proxy = random.choice(self.proxies)
        request.meta['proxy'] = proxy
        self.loger.info('url: %s Using proxy: %s',request.url, request.meta['proxy'])

    def remove_failed_proxy(self, request, spider):
        failed_proxy = request.meta['proxy']
        logging.log(logging.DEBUG, 'Removing failed proxy...')
        try:
            i = 0
            for proxy in self.proxies:
                if proxy in failed_proxy:
                    del self.proxies[i]
                    proxies_num = len(self.proxies)
                    self.loger.info(
                        'Removed failed proxy <%s>, %d proxies left', failed_proxy, proxies_num)
                    if proxies_num < 100:
                        self.query_proxies()
                    return True
                i += 1
        except KeyError:
            logging.log(logging.ERROR, 'Error while removing failed proxy')
        return False

    def process_exception(self, request, exception, spider):
        # if request.url.startswith("http://10.") or getattr(request.meta,'cnt', 0) > 10:
        #     logging.info("request's url is <%s> and had retry %d times", request.url, request.meta.get('cnt',0))
        #     return None
        # else:
        #     if self.remove_failed_proxy(request, spider):
        #         request.meta['cnt'] = request.meta.get('cnt', 0) + 1
        #         logging.info("exception happened")
        #         return request
        if request.url.startswith("http://10.") :
            return None

        if self.remove_failed_proxy(request, spider):
            return request
        if isinstance(exception,TimeoutError):
            self.loger.info("timeout error happened, retry: %s" % request.url)
            return request
        self.loger.info("exception:%s", str(exception))
        return request

    def process_response(self, request, response, spider):
        # really brutal filter
        if response.status == 200:
            return response
        # request.meta['cnt'] = request.meta.get('cnt', 0) + 1
        self.loger.info("%s request status %s, retry again." %(request.url, response.status))
        return request