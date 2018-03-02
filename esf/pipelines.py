# -*- coding: utf-8 -*-

# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://doc.scrapy.org/en/latest/topics/item-pipeline.html
import sqlite3
from scrapy.utils.project import get_project_settings as settings
import logging
from esf.items import IndexItem,PropertyItem,DistrictItem, AgentItem
from twisted.internet import defer
from twisted.enterprise import adbapi
from scrapy.exceptions import NotConfigured
import pymysql
import dj_database_url
import traceback


class SqlitePipeline(object):
    collection_name = "scrapy_items"

    def process_item(self, item, spider):
        self.logger.info("start pipelien %s process spider %s" %(self.collection_name, spider.name))
        if isinstance(item, IndexItem):
            stmt = '''
                insert into index_pages(url, retrived, category,source, project, server, dt, spider) VALUES 
                (?,?,?,?,?,?,?,?)
            '''
            self.cursor.execute(stmt,(item.get("url"),item.get("retrived"),item.get("category"),item.get("source"),
                                      item.get("project"),item.get("server"),item.get("date"),item.get("spider")))

        elif isinstance(item, PropertyItem):

            stmt = '''insert into properties(title, url, price, address, dist_name,
                        subdist_name, dt, source, project, server,spider,agent_name,
                        agent_company,agent_phone,station_name,category, recent_activation) 
                      values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''
            self.cursor.execute(stmt,(item.get("title"),item.get("url"),item.get("price"),
                                      item.get("address"),item.get("dist_name"),item.get("subdist_name")
                                      ,item.get("date"),item.get("source"), item.get("project")
                                      ,item.get("server"),item.get("spider"),
                                      item.get("agent_name"),item.get("agent_company"),item.get("agent_phone")
                                      ,item.get("station_name"),item.get("category"),item.get("recent_activation")))

        elif isinstance(item, DistrictItem):
            stmt = """insert into district_rel (dist_name, subdist_name, url,category,source, project, server, dt, spider)
                        VALUES (?,?,?,?,?,?,?,?,?)
            """
            self.cursor.execute(stmt, (item.get("dist_name"), item.get("subdist_name"), item.get("url"),item.get("category")
                                       ,item.get("source"),item.get("project"), item.get("server"), item.get("date")
                                       ,item.get("spider")))

        elif isinstance(item, AgentItem):
            stmt = """insert into agencies(name,company,address, dist_name,subdist_name, telephone, history_amount,recent_activation
                          ,new_house_amount,second_house_amount,rent_house_amount,register_date,source, project, server, dt, spider)
                      values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """
            self.cursor.execute(stmt,(item.get("name"),item.get("company"),item.get("address") ,item.get("dist_name")
                                      ,item.get("subdist_name"),item.get("telephone"),
                                      item.get("history_amount"),item.get("recent_activation"),
                                      item.get("new_house_amount"), item.get("second_house_amount"),item.get("rent_house_amount"),
                                      item.get("register_date"),
                                      item.get("source"),item.get("project"), item.get("server"), item.get("date"),item.get("spider")))

        self.cnx.commit()
        return item

    def open_spider(self, spider):
        self.cnx = sqlite3.connect(settings().get("STORE_DATABASE"))
        self.cursor = self.cnx.cursor()
        self.cursor.execute("PRAGMA JOURNAL_MODE=WAL")
        self.logger = logging.Logger(__file__)

    def close_spider(self, spider):
        self.cursor.close()
        self.cnx.close()


class MysqlWriter(object):
    @classmethod
    def from_crawler(cls, crawler):
        """Retrieves scrapy crawler and accesses pipelines settings"""
        mysql_url = crawler.settings.get("MYSQL_PIPELINE_URL")
        if not mysql_url:
            raise NotConfigured

        return cls(mysql_url)

    def __init__(self, mysql_url):
        """open a mysql connection pool"""
        self.mysql_url = mysql_url
        self.report_connection_error = None

        conn_kwargs = MysqlWriter.parse_mysql_url(mysql_url)
        self.dbpool = adbapi.ConnectionPool("pymysql", charset='utf8',
                                            use_unicode=True, connect_timeout=5,
                                            **conn_kwargs)
        self.cnx = pymysql.connect(**conn_kwargs)


    def close_spider(self, spider):
        self.dbpool.close()

    @defer.inlineCallbacks
    def process_item(self, item, spider):
        logger = spider.logger
        try:
            ids = self.retrieve_id(spider, item)
            yield self.dbpool.runInteraction(self.do_insert, item, ids)
        except pymysql.OperationalError:
            if self.report_connection_error:
                logger.error("Can't connect to mysql:%s",self.mysql_url)
                self.report_connection_error = False
        except:
            logger.exception(traceback.format_exc()+ "\n%s", item.get("url") or item.get("source") or "no url")

        defer.returnValue(item)

    def retrieve_id(self, spider, item):
        logger = spider.logger
        category_id, station_id, district_id = None, None, None
        try:
            with self.cnx.cursor() as cursor:
                category_sql = "select category_id from estate.category_rel where category_name = %s"
                cursor.execute(category_sql, (item.get("category")))
                category_id = cursor.fetchone()[0]

                district_sql = "select district_id from estate.district_rel where city_name = %s and " \
                               "dist_name = %s and subdist_name = %s"

                cursor.execute(district_sql, (item.get("city_name"), item.get("dist_name"), item.get("subdist_name")))
                district_id = cursor.fetchone()[0]

                station_sql = "select station_id from estate.station_rel where station_name = %s"
                cursor.execute(station_sql, (item.get("station_name")))
                station_id = cursor.fetchone()[0]
        except Exception as e:
            logger.exception("error when retrieve id")

        return category_id, district_id, station_id

    @staticmethod
    def do_insert(tx, item, ids):

        if isinstance(item, PropertyItem):

            stmt = '''insert into properties_temp(title, url, price, address, source, project, server, dt,
                          spider, agent_name, agent_company, agent_phone, recent_activation, 
                          district_id, station_id, category_id) 
                      values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'''
            tx.execute(stmt, (item.get("title"), item.get("url"), item.get("price"), item.get("address"),
                              item.get("source"), item.get("project"), item.get("server"), item.get("dt"),
                              item.get("spider"), item.get("agent_name"), item.get("agent_company"),
                              item.get("agent_phone"), item.get("station_name"), ))

        elif isinstance(item, DistrictItem):
            stmt = """insert into district_rel (dist_name, subdist_name, url,category,source, project, server, dt, spider)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """
            tx.execute(stmt, (
            item.get("dist_name"), item.get("subdist_name"), item.get("url"), item.get("category")
            , item.get("source"), item.get("project"), item.get("server"), item.get("date")
            , item.get("spider")))

        elif isinstance(item, AgentItem):
            stmt = """insert into agencies_temp(name,company,address, dist_name,subdist_name, telephone, history_amount,recent_activation
                          ,new_house_amount,second_house_amount,rent_house_amount,register_date,source, project, server, dt, spider)
                      values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """
            tx.execute(stmt,
                                (item.get("name"), item.get("company"), item.get("address"), item.get("dist_name")
                                 , item.get("subdist_name"), item.get("telephone"),
                                 item.get("history_amount"), item.get("recent_activation"),
                                 item.get("new_house_amount"), item.get("second_house_amount"),
                                 item.get("rent_house_amount"),
                                 item.get("register_date"),
                                 item.get("source"), item.get("project"), item.get("server"), item.get("date"),
                                 item.get("spider")))

    @staticmethod
    def parse_mysql_url(mysql_url):
        params = dj_database_url.parse(mysql_url)
        conn_kwargs = {}
        conn_kwargs["host"] = params["HOST"]
        conn_kwargs["user"] = params["USER"]
        conn_kwargs["passwd"] = params["PASSWORD"]
        conn_kwargs["db"] = params["NAME"]
        conn_kwargs["port"] = params["PORT"]
        # remove items with empty values
        conn_kwargs = dict((k,v) for k,v in conn_kwargs.items() if v)
        return conn_kwargs