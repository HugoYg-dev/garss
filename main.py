import feedparser
import time
import calendar
import email.utils
import os
import re
import pytz
from datetime import datetime
import yagmail
import json
import html
import shutil
from urllib.parse import urlparse
from multiprocessing import Pool, Manager

try:
    from curl_cffi import requests
except ImportError:
    import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, text/html;q=0.7, */*;q=0.5",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache"
}

NON_RETRYABLE_CODES = {401, 403, 404, 410}

def parse_entry_date(entrie):
    """多级容错解析 RSS 条目发布时间与北京时间日期"""
    pub_parsed = entrie.get("published_parsed") or entrie.get("updated_parsed") or entrie.get("created_parsed")
    if pub_parsed:
        try:
            ts = float(calendar.timegm(pub_parsed))
            beijing_tz = pytz.timezone('Asia/Shanghai')
            date_str = datetime.fromtimestamp(ts, beijing_tz).strftime("%Y-%m-%d")
            return ts, date_str, True
        except Exception:
            pass

    # 兜底：feedparser 未能解析时尝试原始字符串解析
    raw_date = entrie.get("published") or entrie.get("updated") or entrie.get("pubDate")
    if raw_date and isinstance(raw_date, str):
        try:
            dt = email.utils.parsedate_to_datetime(raw_date)
            ts = float(dt.timestamp())
            beijing_tz = pytz.timezone('Asia/Shanghai')
            date_str = datetime.fromtimestamp(ts, beijing_tz).strftime("%Y-%m-%d")
            return ts, date_str, True
        except Exception:
            pass

    return 0.0, "", False

def get_rss_info(feed_url, index, rss_info_list):
    result = {"result": []}
    
    # 智能修正已下线的私有 RSSHub 域名，自动映射复活 17 个关键源
    actual_url = feed_url
    rsshub_mirror = os.environ.get("RSSHUB_BASE_URL", "https://rsshub.app")
    if "rsshub.v2fy.com" in actual_url:
        actual_url = actual_url.replace("https://rsshub.v2fy.com", rsshub_mirror)

    # 代理配置探测
    proxies = {}
    proxy_url = os.environ.get("RSS_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    for i in range(3):
        try:
            timeout_sec = (i + 1) * 8
            req_kwargs = {"headers": DEFAULT_HEADERS, "timeout": timeout_sec}
            if proxies:
                req_kwargs["proxies"] = proxies

            if "linux.do" in actual_url:
                req_kwargs["headers"] = req_kwargs.get("headers", DEFAULT_HEADERS).copy()
                req_kwargs["headers"]["User-Agent"] = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

            try:
                # 使用较新的 Chrome 浏览器指纹绕过 Cloudflare 防火墙
                resp = requests.get(actual_url, impersonate="chrome124", **req_kwargs)
            except TypeError:
                # 若降级为原生 requests，无 impersonate 参数
                resp = requests.get(actual_url, **req_kwargs)

            # 遇到明确拒绝或不存在的状态码，立即快速熔断，绝不无效重试
            if resp.status_code in NON_RETRYABLE_CODES:
                print(f"[{index}] {feed_url} 返回不可恢复状态码 HTTP {resp.status_code}，快速熔断。")
                break

            resp.raise_for_status()

            # 解析 RSS 响应
            feed = feedparser.parse(resp.content)
            feed_entries = feed.get("entries", [])
            
            # 若内容不是标准 RSS（如部分防火墙质询的 HTML 页面）
            if not feed_entries and feed.get("bozo", 0) == 1:
                print(f"[{index}] {feed_url} 响应内容非有效 XML/RSS 数据流。")
                break

            entries_to_process = feed_entries[:10] if len(feed_entries) > 10 else feed_entries
            for entrie in entries_to_process:
                title = entrie.get("title", "").replace("\n", "").replace("\r", "")
                link = entrie.get("link", "")
                ts, date_str, has_date = parse_entry_date(entrie)

                result["result"].append({
                    "title": title,
                    "link": link,
                    "date": date_str,
                    "timestamp": ts,
                    "has_explicit_date": has_date
                })
            break
        except Exception as e:
            print(f"[{index}] {feed_url} 第 {i+1} 次请求出错==>>", e)
            if i < 2:
                time.sleep(1)

    rss_info_list[index] = result["result"]
    print("本次爬取==》》", feed_url, "<<<===", index, len(result["result"]))
    # 剩余数量
    remaining_amount = 0
    for tmp_rss_info_atom in rss_info_list:
        if isinstance(tmp_rss_info_atom, int):
            remaining_amount = remaining_amount + 1
            
    print("当前进度 | 剩余数量", remaining_amount, "已完成==>>", len(rss_info_list) - remaining_amount)
    return result["result"]
    


def send_mail(email, title, contents):
    # 判断secret.json是否存在
    user = ""
    password = ""
    host = ""
    try:
        if(os.environ["MAIL_USER"]):
            user = os.environ["MAIL_USER"]
        if(os.environ["MAIL_PASSWORD"]):
            password = os.environ["MAIL_PASSWORD"]
        if(os.environ["MAIL_HOST"]):
            host = os.environ["MAIL_HOST"]
    except KeyError:
        print("无法获取github的secrets配置信息,开始使用本地变量")
        if(os.path.exists(os.path.join(os.getcwd(),"secret.json"))):
            with open(os.path.join(os.getcwd(),"secret.json"),'r') as load_f:
                load_dict = json.load(load_f)
                user = load_dict["user"]
                password = load_dict["password"]
                host = load_dict["host"]
                # print(load_dict)
        else:
            print("无法获取发件人信息")
    
    # 连接邮箱服务器
    # yag = yagmail.SMTP(user=user, password=password, host=host)
    yag = yagmail.SMTP(user = user, password = password, host=host)
    # 发送邮件
    yag.send(email, title, contents)

def format_item_link(item, is_new):
    """安全格式化 Markdown 表格行超链接，根除尾部悬挂管道符问题"""
    title = item.get("title", "").replace("|", r"\|").replace("[", r"\[").replace("]", r"\]")
    date_str = item.get("date", "")
    link = item.get("link", "")
    if is_new:
        suffix = f" 🌈 {date_str}" if date_str else " 🌈"
    else:
        suffix = f" | {date_str}" if date_str else ""
    return f"[{title}{suffix}]({link})"

def get_last_run_timestamp(readme_path="README.md"):
    try:
        target = os.path.join(os.getcwd(), readme_path)
        if os.path.exists(target):
            with open(target, "r", encoding="utf-8") as f:
                content = f.read()
            m = re.search(r"生产时间\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", content)
            if m:
                beijing_tz = pytz.timezone('Asia/Shanghai')
                dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                dt = beijing_tz.localize(dt)
                return dt.timestamp()
    except Exception:
        pass
    return None

def replace_readme():
    new_edit_readme_md = ["", ""]
    current_date_news_index = [""]

    # 读取EditREADME.md
    print("replace_readme")
    new_num = 0
    with open(os.path.join(os.getcwd(),"EditREADME.md"),'r') as load_f:
        edit_readme_md = load_f.read()

    new_edit_readme_md[0] = edit_readme_md
    before_info_list =  re.findall(r'\{\{latest_content\}\}.*\[订阅地址\]\(.*\)' ,edit_readme_md)
    # 填充统计RSS数量
    new_edit_readme_md[0] = new_edit_readme_md[0].replace("{{rss_num}}", str(len(before_info_list)))
    # 填充统计时间
    ga_rss_datetime = datetime.fromtimestamp(int(time.time()),pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
    new_edit_readme_md[0] = new_edit_readme_md[0].replace("{{ga_rss_datetime}}", str(ga_rss_datetime))

    # 使用进程池进行数据获取，获得rss_info_list
    before_info_list_len = len(before_info_list)
    rss_info_list = Manager().list(range(before_info_list_len))
    print('初始化完毕==》', rss_info_list)

    # 创建一个最多开启8进程的进程池
    po = Pool(8)

    for index, before_info in enumerate(before_info_list):
        # 获取link
        link = re.findall(r'\[订阅地址\]\((.*)\)', before_info)[0]
        po.apply_async(get_rss_info,(link, index, rss_info_list))

    # 关闭进程池,不再接收新的任务,开始执行任务
    po.close()

    # 主进程等待所有子进程结束
    po.join()
    print("----结束----", rss_info_list)

    # 动态自适应时间窗口：以上次 README 生产时间为下限（最大28小时，防止重复推送并容忍排队延迟）
    TIME_WINDOW_SECONDS = 28 * 3600
    FUTURE_TOLERANCE_SECONDS = 3600
    now_ts = time.time()
    last_run_ts = get_last_run_timestamp()
    window_start_ts = min(max(now_ts - TIME_WINDOW_SECONDS, last_run_ts), now_ts) if last_run_ts else (now_ts - TIME_WINDOW_SECONDS)

    def is_new_entry(item):
        try:
            ts = float(item.get("timestamp", 0))
        except (ValueError, TypeError):
            ts = 0.0
        if ts > 0:
            return window_start_ts <= ts <= (now_ts + FUTURE_TOLERANCE_SECONDS)
        # 无有效时间戳的文章坚决不标记为新，根除幽灵文章每日重复推送
        return False

    for index, before_info in enumerate(before_info_list):
        # 获取link
        link = re.findall(r'\[订阅地址\]\((.*)\)', before_info)[0]
        # 生成超链接
        rss_info = rss_info_list[index]
        if not isinstance(rss_info, list):
            rss_info = []

        latest_content = ""
        parse_result = urlparse(link)
        scheme_netloc_url = str(parse_result.scheme) + "://" + str(parse_result.netloc)
        latest_content = f"[暂无法通过爬虫获取信息, 点击进入源网站主页]({scheme_netloc_url})"

        # 加入到索引
        try:
            for rss_info_atom in rss_info:
                if is_new_entry(rss_info_atom):
                    new_num = new_num + 1
                    if (new_num % 2) == 0:
                        current_date_news_index[0] = current_date_news_index[0] + "<div style='line-height:3;' ><a href='" + html.escape(rss_info_atom["link"], quote=True) + "' " + 'style="line-height:2;text-decoration:none;display:block;color:#584D49;">' + "🌈 ‣ " + html.escape(rss_info_atom["title"]) + " | 第" + str(new_num) +"篇" + "</a></div>"
                    else:
                        current_date_news_index[0] = current_date_news_index[0] + "<div style='line-height:3;background-color:#FAF6EA;' ><a href='" + html.escape(rss_info_atom["link"], quote=True) + "' " + 'style="line-height:2;text-decoration:none;display:block;color:#584D49;">' + "🌈 ‣ " + html.escape(rss_info_atom["title"]) + " | 第" + str(new_num) +"篇" + "</a></div>"

        except Exception as e:
            print("An exception occurred in news index:", e)

        if len(rss_info) > 0:
            latest_content = format_item_link(rss_info[0], is_new_entry(rss_info[0]))

        if len(rss_info) > 1:
            latest_content = latest_content + "<br/>" + format_item_link(rss_info[1], is_new_entry(rss_info[1]))

        # 生成after_info
        after_info = before_info.replace("{{latest_content}}", latest_content)
        print("====latest_content==>", latest_content)
        # 替换edit_readme_md中的内容
        new_edit_readme_md[0] = new_edit_readme_md[0].replace(before_info, after_info)
    
    # 替换EditREADME中的索引
    new_edit_readme_md[0] = new_edit_readme_md[0].replace("{{news}}", current_date_news_index[0])
    # 替换EditREADME中的新文章数量索引
    new_edit_readme_md[0] = new_edit_readme_md[0].replace("{{new_num}}", str(new_num))
    # 添加CDN
    new_edit_readme_md[0] = new_edit_readme_md[0].replace("./_media", "https://cdn.jsdelivr.net/gh/zhaoolee/garss/_media")
        
    # 将新内容
    with open(os.path.join(os.getcwd(),"README.md"),'w') as load_f:
        load_f.write(new_edit_readme_md[0])
    

    mail_re = r'邮件内容区开始>([.\S\s]*)<邮件内容区结束'
    reResult = re.findall(mail_re, new_edit_readme_md[0])
    new_edit_readme_md[1] = reResult

    
    return new_edit_readme_md

# 将README.md复制到docs中

def cp_readme_md_to_docs():
    shutil.copyfile(os.path.join(os.getcwd(),"README.md"), os.path.join(os.getcwd(), "docs","README.md"))
    
def cp_media_to_docs():
    if os.path.exists(os.path.join(os.getcwd(), "docs","_media")):
        shutil.rmtree(os.path.join(os.getcwd(), "docs","_media"))	
    shutil.copytree(os.path.join(os.getcwd(),"_media"), os.path.join(os.getcwd(), "docs","_media"))

def get_email_list():
    email_list = []
    with open(os.path.join(os.getcwd(),"tasks.json"),'r') as load_f:
        load_dic = json.load(load_f)
        for task in load_dic["tasks"]:
            email_list.append(task["email"])
    return email_list

# 创建opml订阅文件

def create_opml():

    result = "";
    result_v1 = "";

    # <outline text="CNET News.com" description="Tech news and business reports by CNET News.com. Focused on information technology, core topics include computers, hardware, software, networking, and Internet media." htmlUrl="http://news.com.com/" language="unknown" title="CNET News.com" type="rss" version="RSS2" xmlUrl="http://news.com.com/2547-1_3-0-5.xml"/>

    with open(os.path.join(os.getcwd(),"EditREADME.md"),'r') as load_f:
        edit_readme_md = load_f.read();

        ## 将信息填充到opml_info_list
        opml_info_text_list =  re.findall(r'.*\{\{latest_content\}\}.*\[订阅地址\]\(.*\).*' ,edit_readme_md);

        for opml_info_text in opml_info_text_list:


            # print('==', opml_info_text)

            opml_info_text_format_data = re.match(r'\|(.*)\|(.*)\|(.*)\|(.*)\|.*\[订阅地址\]\((.*)\).*\|',opml_info_text)

            # print("data==>>", opml_info_text_format_data)

            # print("总信息", opml_info_text_format_data[0].strip())
            # print("编号==>>", opml_info_text_format_data[1].strip())
            # print("text==>>", opml_info_text_format_data[2].strip())
            # print("description==>>", opml_info_text_format_data[3].strip())
            # print("data004==>>", opml_info_text_format_data[4].strip())
            print('##',opml_info_text_format_data[2].strip())
            print(opml_info_text_format_data[3].strip())
            print(opml_info_text_format_data[5].strip())
            

            opml_info = {}
            opml_info["text"] = opml_info_text_format_data[2].strip()
            opml_info["description"] = opml_info_text_format_data[3].strip()
            opml_info["htmlUrl"] = opml_info_text_format_data[5].strip()
            opml_info["title"] = opml_info_text_format_data[2].strip()
            opml_info["xmlUrl"] = opml_info_text_format_data[5].strip()

            # print('opml_info==>>', opml_info);
            


            opml_info_text = '<outline  text="{text}" description="{description}" htmlUrl="{htmlUrl}" language="unknown" title="{title}" type="rss" version="RSS2" xmlUrl="{xmlUrl}"/>'

            opml_info_text_v1 = '      <outline text="{title}" title="{title}" type="rss"  \n            xmlUrl="{xmlUrl}" htmlUrl="{htmlUrl}"/>'

            opml_info_text =  opml_info_text.format(
                text=opml_info["text"], 
                description=opml_info["description"], 
                htmlUrl = opml_info["htmlUrl"],
                title=opml_info["title"],
                xmlUrl=opml_info["xmlUrl"]
            )

            opml_info_text_v1 =  opml_info_text_v1.format(
                htmlUrl = opml_info["htmlUrl"],
                title=opml_info["title"],
                xmlUrl=opml_info["xmlUrl"]
            )

            result = result + opml_info_text + "\n"

            result_v1 = result_v1 + opml_info_text_v1 + "\n"
    
    zhaoolee_github_garss_subscription_list = "";
    with open(os.path.join(os.getcwd(),"rss-template-v2.txt"),'r') as load_f:
        zhaoolee_github_garss_subscription_list_template = load_f.read();
        GMT_FORMAT = '%a, %d %b %Y %H:%M:%S GMT'
        date_created = datetime.utcnow().strftime(GMT_FORMAT);
        date_modified = datetime.utcnow().strftime(GMT_FORMAT);
        zhaoolee_github_garss_subscription_list = zhaoolee_github_garss_subscription_list_template.format(result=result, date_created=date_created, date_modified=date_modified);
        # print(zhaoolee_github_garss_subscription_list);

    # 将内容写入
    with open(os.path.join(os.getcwd(),"zhaoolee_github_garss_subscription_list_v2.opml"),'w') as load_f:
        load_f.write(zhaoolee_github_garss_subscription_list)

    zhaoolee_github_garss_subscription_list_v1 = ""
    with open(os.path.join(os.getcwd(),"rss-template-v1.txt"),'r') as load_f:
        zhaoolee_github_garss_subscription_list_template = load_f.read();
        zhaoolee_github_garss_subscription_list_v1 = zhaoolee_github_garss_subscription_list_template.format(result=result_v1);
        # print(zhaoolee_github_garss_subscription_list_v1);

    # 将内容写入
    with open(os.path.join(os.getcwd(),"zhaoolee_github_garss_subscription_list_v1.opml"),'w') as load_f:
        load_f.write(zhaoolee_github_garss_subscription_list_v1)




        
    # print(result)

def create_json():
    result = {"garssInfo": []}
    with open(os.path.join(os.getcwd(),"EditREADME.md"),'r') as load_f:
        edit_readme_md = load_f.read();
        ## 将信息填充到opml_info_list
        opml_info_text_list =  re.findall(r'.*\{\{latest_content\}\}.*\[订阅地址\]\(.*\).*' ,edit_readme_md);
        for opml_info_text in opml_info_text_list:
            opml_info_text_format_data = re.match(r'\|(.*)\|(.*)\|(.*)\|(.*)\|.*\[订阅地址\]\((.*)\).*\|',opml_info_text)
            opml_info = {}
            opml_info["description"] = opml_info_text_format_data[3].strip()
            opml_info["title"] = opml_info_text_format_data[2].strip()
            opml_info["xmlUrl"] = opml_info_text_format_data[5].strip()
            result["garssInfo"].append(opml_info)
    with open("./garssInfo.json","w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

def main():
    create_json()
    create_opml()
    readme_md = replace_readme()
    cp_readme_md_to_docs()
    cp_media_to_docs()
    email_list = get_email_list()

    mail_re = r'邮件内容区开始>([.\S\s]*)<邮件内容区结束'
    reResult = re.findall(mail_re, readme_md[0])

    try:
        send_mail(email_list, "嘎!RSS订阅", reResult)
    except Exception as e:
        print("==邮件设信息置错误===》》", e)


if __name__ == "__main__":
    main()