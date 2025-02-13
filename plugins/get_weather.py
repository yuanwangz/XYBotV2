import tomllib

import aiohttp
import jieba

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase


class GetWeather(PluginBase):
    description = "获取天气"
    author = "HenryXiaoYang"
    version = "1.0.0"
    
    priority = 1
    mutex_group = "text_response"

    def __init__(self):
        super().__init__()

        with open("plugins/all_in_one_config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["GetWeather"]

        self.enable = config["enable"]
        self.command_format = config["command-format"]
        self.api_key = config["api-key"]

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return False

        if "天气" not in message["Content"]:
            return False

        content = str(message["Content"]).replace(" ", "")
        command = list(jieba.cut(content))

        if len(command) == 1:
            await bot.send_at_message(message["FromWxid"], "\n" + self.command_format, [message["SenderWxid"]])
            return True  # 消息已处理

        command.remove("天气")
        request_loc = "".join(command)

        geo_api_url = f'https://geoapi.qweather.com/v2/city/lookup?key={self.api_key}&number=1&location={request_loc}'
        conn_ssl = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.request('GET', url=geo_api_url, connector=conn_ssl) as response:
            geoapi_json = await response.json()
            await conn_ssl.close()

        if geoapi_json['code'] == '404':
            await bot.send_at_message(message["FromWxid"], "\n⚠️查无此地！", [message["SenderWxid"]])
            return True  # 消息已处理

        elif geoapi_json['code'] != '200':
            await bot.send_at_message(message["FromWxid"], f"\n⚠️请求失败\n{geoapi_json}", [message["SenderWxid"]])
            return True  # 消息已处理

        country = geoapi_json["location"][0]["country"]
        adm1 = geoapi_json["location"][0]["adm1"]
        adm2 = geoapi_json["location"][0]["adm2"]
        city_id = geoapi_json["location"][0]["id"]

        # 请求现在天气api
        conn_ssl = aiohttp.TCPConnector(verify_ssl=False)
        now_weather_api_url = f'https://devapi.qweather.com/v7/weather/now?key={self.api_key}&location={city_id}'
        async with aiohttp.request('GET', url=now_weather_api_url, connector=conn_ssl) as response:
            now_weather_api_json = await response.json()
            await conn_ssl.close()

        # 请求预报天气api
        conn_ssl = aiohttp.TCPConnector(verify_ssl=False)
        weather_forecast_api_url = f'https://devapi.qweather.com/v7/weather/7d?key={self.api_key}&location={city_id}'
        async with aiohttp.request('GET', url=weather_forecast_api_url, connector=conn_ssl) as response:
            weather_forecast_api_json = await response.json()
            await conn_ssl.close()

        out_message = self.compose_weather_message(country, adm1, adm2, now_weather_api_json, weather_forecast_api_json)
        await bot.send_at_message(message["FromWxid"], "\n" + out_message, [message["SenderWxid"]])
        return True  # 消息已处理

    @staticmethod
    def compose_weather_message(country, adm1, adm2, now_weather_api_json, weather_forecast_api_json):
        update_time = now_weather_api_json['updateTime']
        now_temperature = now_weather_api_json['now']['temp']
        now_feelslike = now_weather_api_json['now']['feelsLike']
        now_weather = now_weather_api_json['now']['text']
        now_wind_direction = now_weather_api_json['now']['windDir']
        now_wind_scale = now_weather_api_json['now']['windScale']
        now_humidity = now_weather_api_json['now']['humidity']
        now_precip = now_weather_api_json['now']['precip']
        now_visibility = now_weather_api_json['now']['vis']
        now_uvindex = weather_forecast_api_json['daily'][0]['uvIndex']

        message = (
            f"----- Bot -----\n"
            f"{country}{adm1}{adm2} 实时天气☁️\n"
            f"⏰更新时间：{update_time}\n\n"
            f"🌡️当前温度：{now_temperature}℃\n"
            f"🌡️体感温度：{now_feelslike}℃\n"
            f"☁️天气：{now_weather}\n"
            f"☀️紫外线指数：{now_uvindex}\n"
            f"🌬️风向：{now_wind_direction}\n"
            f"🌬️风力：{now_wind_scale}级\n"
            f"💦湿度：{now_humidity}%\n"
            f"🌧️降水量：{now_precip}mm/h\n"
            f"👀能见度：{now_visibility}km\n\n"
            f"☁️未来3天 {adm2} 天气：\n"
        )
        for day in weather_forecast_api_json['daily'][1:4]:
            date = '.'.join([i.lstrip('0') for i in day['fxDate'].split('-')[1:]])
            weather = day['textDay']
            max_temp = day['tempMax']
            min_temp = day['tempMin']
            uv_index = day['uvIndex']
            message += f'{date} {weather} 最高🌡️{max_temp}℃ 最低🌡️{min_temp}℃ ☀️紫外线:{uv_index}\n'

        return message
