import requests
import urllib3
import urllib.parse
import os
import tarfile
import time

from urllib.parse import urlparse

urllib3.disable_warnings()
proxies = {
    # 'http': 'http://127.0.0.1:8080',
    # 'https': 'http://127.0.0.1:8080'
}
TimeOut = 120
TimeOutDownload = 10 * 60
Headers = {"User-Agent":"Mozilla/5.0 (Macintosh; Intel Windows OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

search_value = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k',
                'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z']
images_list = {}
Version = 2  # harbor api 版本
TarSize = 1024 * 1024 * 10


def logger(log="green", text=""):
    if log == "green":
        print("\033[92m{}\033[0m".format(text))
    if log == "red":
        print("\033[91m{}\033[0m".format(text))
    if log == "white":
        print("\033[37m{}\033[0m".format(text))
    if log == "yellow":
        print("\033[33m{}\033[0m".format(text))
    if log == "banner":
        print("\033[1;36m{}\033[0m".format(text))


def search_list(url):
    for i in search_value:
        count = 0
        if Version == 1:
            search_url = urllib.parse.urljoin(url, '/api/search?q=' + str(i))
        else:
            search_url = urllib.parse.urljoin(url, '/api/v2.0/search?q=' + str(i))
        logger('yellow', '[+] search -> ' + str(i))
        try:
            response = requests.get(search_url, verify=False, timeout=TimeOut, proxies=proxies, headers=Headers)
            json1 = response.json()
            for ii in json1['repository']:
                images_key = ii['project_id']
                images_value = ii['repository_name']
                images_list[images_value] = images_key
                count += 1
        except Exception as e:
            logger('red', '[!] Search error: ' + str(e))
        logger('green', f'[+] 关键字:{i} 共计搜索到 {count} 个镜像仓库')
    logger('green', f'[+]共计搜索到 {len(images_list)} 个镜像仓库')


def bytes_to_megabytes(bytes):
    megabytes = bytes / (1024 * 1024)
    return round(megabytes, 2)


def write_to_file(file_name, data):
    mode = 'a' if os.path.exists(file_name) else 'w'
    with open(file_name, mode) as file:
        file.write(data)


docker_result = []


def project_list(url):
    for key in images_list:
        try:
            time.sleep(0.2)
            value = key.split('/')
            # v2 = '/'.join(value[1:])
            if Version == 1:
                url2 = f'{url}/api/repositories/{key}/tags?detail=true'
            else:
                url2 = f'{url}/api/v2.0/projects/{value[0]}/repositories/{value[-1]}/artifacts?with_tag=true&with_scan_overview=true&with_label=true&page_size=15&page=1'
            response = requests.get(url=url2, verify=False, proxies=proxies, timeout=TimeOut, headers=Headers)
            json1 = response.json()
            if len(json1) == 0:
                logger('yellow', f"[-]{value[0]} 为空镜像")
                continue
            digest = json1[0]['digest']
            push_time = json1[0]['push_time']
            size = json1[0]['size']
            size = bytes_to_megabytes(int(size))
            pustr = f'{key}@{digest}\tPushTime: {push_time}\tSize: {size} MB'
            logger('green', f'{pustr}')
            docker_result.append(pustr)
        except Exception as e:
            logger('red', '[!] project_list error: ' + str(e))
    result1 = "\n".join(docker_result)
    parsed_url = urlparse(url)
    write_to_file(file_name=f"{parsed_url.hostname}-result.txt", data=result1)


def get_token(url, repository, repository_name):
    url2 = f'{url}/service/token?scope=repository%3A{repository}%2F{repository_name}%3Apull&service=harbor-registry'
    try:
        response = requests.get(url=url2, verify=False, proxies=proxies, timeout=TimeOut, headers=Headers)
        json1 = response.json()
        token = json1['token']
    except Exception as e:
        logger('red', '[!] GetToken error: ' + str(e))
        return
    return token


def get_manifests(url, repository, repository_name, tag):
    token = get_token(url, repository, repository_name)
    if token is None:
        return
    url2 = f'{url}/v2/{repository}/{repository_name}/manifests/{tag}'
    try:
        headers = {
            'Authorization': f'Bearer {token}',
            "User-Agent":"Mozilla/5.0 (Macintosh; Intel Windows OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        response = requests.get(url=url2, verify=False, proxies=proxies, timeout=TimeOut, headers=headers)
        json1 = response.json()
        config_digest = json1["config"]["digest"]
        if config_digest is None:
            logger('yellow', '[!] get_manifests config_digest error: ' + url2)
            return
        logger('yellow', f"[+] Download {repository}/{repository_name} manifests.json")
        download_tar(url, token, repository, repository_name, config_digest, True)
        for ii in json1["layers"]:
            digest = ii["digest"]
            size = ii["size"]
            size1 = bytes_to_megabytes(int(size))
            logger('green', f"[+] Info {repository}/{repository_name} {digest} {size1} MB")
            if TarSize < int(size):
                logger('green', f"[+] Download {repository}/{repository_name} {digest} {size1} MB")
                download_tar(url, token, repository, repository_name, digest, False)
    except Exception as e:
        logger('red', '[!] get_manifests error: ' + str(e))
        return


def extract_tar_gz(tar_gz_file, extract_dir):
    try:
        with tarfile.open(tar_gz_file, "r:gz") as tar:
            tar.extractall(path=extract_dir)
        logger(f'green', f'[+]  {tar_gz_file}解压成功')
        os.remove(tar_gz_file)
    except tarfile.ReadError:
        logger('red', f'[!] {tar_gz_file} 解压失败：文件格式不正确')
    except FileNotFoundError:
        logger('red', f'[!] {tar_gz_file} 解压失败：文件不存在')
    except Exception as e:
        logger('red', f'[!] {tar_gz_file} 解压失败：解压过程中出现错误：{e}')


def download_tar(url, token, repository, repository_name, tag, json1):
    headers = {
        'Authorization': f'Bearer {token}',
        "User-Agent":"Mozilla/5.0 (Macintosh; Intel Windows OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    url2 = f"{url}/v2/{repository}/{repository_name}/blobs/{tag}"
    try:
        response = requests.get(url=url2, verify=False, headers=headers, stream=True)
        if response.status_code == 200:
            save_dir = f"./target/{repository}_{repository_name}"
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
            if json1:
                filename = save_dir + '/manifests.json'
            else:
                filename = save_dir + '/' + tag + ".tar.gz"
            with open(filename, 'wb') as file:
                for chunk in response.iter_content(chunk_size=1024 * 10):  # 按照 1KB 的大小逐块下载文件
                    if chunk:
                        file.write(chunk)
            if not json1:
                extract_tar_gz(filename, save_dir)
    except Exception as e:
        logger('red', '[!] get_manifests error: ' + str(e))
        return


def read_dockerfile(path):
    list1 = []
    with open(path, 'r') as f:
        for line in f.readlines():
            line = line.strip()
            line = line.strip("\n")
            if line == "":
                continue
            list1.append(line)
    return list1


def docker_pull_main(filename):
    list1 = read_dockerfile(filename)
    if len(list1) == 0:
        logger('red', '[!] Get dockerfile error')
        return
    for i in list1:
        list2 = i.split("\t")
        v1 = list2[0]
        list3 = v1.split("@")
        v2 = list3[0].rstrip('/')
        list4 = v2.split("/")
        repository = list4[0]
        repository_name = list4[-1]
        tag = list3[1]
        # print(repository, repository_name, tag)
        get_manifests(url1, repository, repository_name, tag)


if __name__ == '__main__':
    if not os.path.exists("target"):
        os.makedirs("target")
    url1 = "https://x.x.x.x:/"  # 目标harbor地址
    Version = 2   # 版本号


    # search_list(url1)  # 搜索镜像并将结果保存到文件
    # project_list(url1)

    # docker_pull_main("保存的文本文件.txt")  # 下载镜像
