#!/usr/bin/env python3

import ssl
import sys, getopt
import requests
import time
import datetime
import json
import os, fnmatch
import re
import shutil
from urllib.parse import urlparse, unquote

# globals
article_file_indicator = '@article.*'
manual_file_indicator = '@toc.*'
image_folder_indicator = '@images'
attach_folder_indicator = '@attachments'

# new code section: Global trackers for incremental deletions
TRACKED_PATHS = set()
FULLY_PROCESSED_FOLDERS = set()

# new code section: Helper to track all valid paths we touch or skip
def track_path(path):
    if path:
        abs_path = os.path.abspath(path)
        TRACKED_PATHS.add(abs_path)
        parent = os.path.dirname(abs_path)
        while parent and parent != os.path.dirname(parent):
            TRACKED_PATHS.add(parent)
            parent = os.path.dirname(parent)

# new code section: Helper to parse ScreenSteps timestamps
def get_source_mtime(date_str):
    if not date_str:
        return None
    try:
        date_str = date_str.replace('Z', '+00:00')
        return datetime.datetime.fromisoformat(date_str).timestamp()
    except Exception:
        return None

# these are the handlebars you can use in an article file
article_handlebars = [
    "id",
    "title",
    "manual_id",
    "chapter_id",
    "last_edited_by",
    "last_edited_at",
    "meta_title",
    "meta_description",
    "meta_search",
    "created_at"]

# these are the handlebars you can use in manual file
# {{title}} outside of any blocks for manual title
# {{chapter}} to start and end the chapter, then {{title}} in the block
# {{article}} to start and end the manual, then {{title}} and {{link}} in the block

# Define the help message here.
def print_help():
    print("""
    Usage:
    run -n <account_name> -u <user_id> -p <token_password>
    [-t <template_folder>]
    [-o <output_folder>]
    [-s <site_id>]
    [-m <manual_id>]
    [-a <article_id>]
    [-M <manual_file_name]
    [-i object_identifier]
    [-I]

    Explanations:
    -n This is used for the name of the account (http://<account_name>.screenstepslive.com)
    -u Your user ID
    -p Your API token or password
    -t The folder with your templates (optional)
    -o The folder you would like with outputs (optional)
    -s If you'd like to only download one site, specify the ID here (optional)
    -m If you'd like to only download one manual, specify the ID here (optional)
    -a If you'd like to only download one article, specify the ID here (optional)
    -M Pass in a specific name to use for the manual file. Must pass in the -m parameter.
    -i Specifies how the site, manual, and article files should be named. By default the "id" from ScreenSteps is used. You can set this to "title" or "title_id". "title_id" will use the name with " [ID]" appended to the end.
    -I Incremental mode. Skips downloading files if local files are newer than the source, and removes files no longer in the source. # new code section
    
    Examples:
    run -n customerknowledge -u mikey -p mypassword -s 15226
    run -n myaccount -u johnsmith -p notAgoodPassword -a 21234
    """)

def make_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)
    # new code section: Track created directory
    track_path(directory)

def download_file(directory, url, source_mtime=None, incremental=False): # new code section: parameters added
    short_path = unquote(url.split('/')[-1].split('?')[0]) # Remove any url encoding
    local_filename = os.path.join(directory, short_path)
    
    # new code section: Track and check if we can skip download
    track_path(local_filename)
    if incremental and source_mtime and os.path.exists(local_filename):
        if os.path.getmtime(local_filename) >= source_mtime:
            return short_path

    r = requests.get(url, stream=True)
    with open(local_filename, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)
    return short_path

def find_file(pattern, path):
    result = []
    for root, dirs, files in os.walk(path):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                result.append(os.path.join(root, name))
    return result

def find_dirs(pattern, path):
    result = []
    for root, dirs, files in os.walk(path):
        for dirname in dirs:
            if pattern in dirname.split():
                result.append(os.path.join(root, dirname))
    return result

def split_path(path):
    allparts = []
    while 1:
        parts = os.path.split(path)
        if parts[0] == path:  # sentinel for absolute paths
            allparts.insert(0, parts[0])
            break
        elif parts[1] == path: # sentinel for relative paths
            allparts.insert(0, parts[1])
            break
        else:
            path = parts[0]
            allparts.insert(0, parts[1])
    return allparts

def remove_list_overlap(larger,smaller):
    for myitem in smaller:
        if myitem in larger:
            larger.remove(myitem)
    return larger

def find_relative_path(thispath,template_folder):
    relative_path = remove_list_overlap(split_path(thispath),split_path(template_folder))
    if len(relative_path[:-1]) > 0:
        relative_path = os.path.join(*relative_path[:-1])
    else:
        relative_path = ''
    return relative_path

def find_at_file_path(thispath,template_folder):
    relative_path = remove_list_overlap(split_path(thispath),split_path(template_folder))
    return os.path.join(*relative_path)

def remove_directory(directory):
    if os.path.exists(directory):
        shutil.rmtree(directory)

def remove_directories(directories):
    for directory in directories:
        remove_directory(directory)

def remove_found_files(files):
    for name in files:
        if os.path.exists(name):
            os.remove(name)

def write_file(directory, name, rawtext, source_mtime=None, incremental=False): # new code section: parameters added
    file_path = os.path.join(directory, name)
    
    # new code section: Track and check if we can skip writing
    track_path(file_path)
    if incremental and source_mtime and os.path.exists(file_path):
        if os.path.getmtime(file_path) >= source_mtime:
            return

    with open(file_path, 'wb+') as f:
        f.write(rawtext.encode('utf-8'))

def copy_and_overwrite(from_path, to_path, incremental=False): # new code section: parameters added
    # new code section: Safely copy templates in incremental mode
    if incremental:
        import sys
        if sys.version_info >= (3, 8):
            shutil.copytree(from_path, to_path, dirs_exist_ok=True)
        else:
            if not os.path.exists(to_path):
                shutil.copytree(from_path, to_path)
    else:
        if os.path.exists(to_path):
            shutil.rmtree(to_path)
        shutil.copytree(from_path, to_path)
        
    # new code section: Ensure copied template files are tracked so they aren't deleted later
    for root, dirs, files in os.walk(to_path):
        track_path(root)
        for f in files:
            track_path(os.path.join(root, f))

def read_file(path):
    with open(path) as f:
        contents = f.read()
    return contents

def _decode(var):
    # all strings are unicode now
    return str(var)

def prepare_for_filename(string):
        return "".join([c for c in string if c.isalpha() or c.isdigit() or c==' ']).rstrip()

def _print(var):
    return var

def main(argv):
    # Define variables we need.
    site_name = '' #n / site_name
    user_id = ''#u / user_id
    api_token = ''#p / password
    template_folder = '' #t / template
    output_folder = '' #o / output
    site_id = ''#s / site
    manual_id = ''#m / manual
    article_id = ''#a / article
    manual_file_name = ''#M / manual_file_name
    object_identifier = 'id'#i / object_identifier
    incremental = False #I / incremental # new code section
    try:
        # new code section: added "I" and "incremental"
        opts, args = getopt.getopt(argv,"hIn:u:p:t:o:s:m:a:M:i:",["incremental","site_name=","user_id=","password=","template_folder=","output_folder=","site_id=","manual_id=","article_id=","manual_file_name=","object_identifier="])
    except getopt.GetoptError:
        print('use "run.py -h" for help')
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print_help()
            sys.exit()
        elif opt in ("-I", "--incremental"): # new code section
            incremental = True
        elif opt in ("-n", "--site_name"):
            site_name = arg
        elif opt in ("-u", "--user_id"):
            user_id = arg
        elif opt in ("-p", "--password"):
            api_token = arg
        elif opt in ("-t", "--template_folder"):
            template_folder = arg
        elif opt in ("-o", "--output_folder"):
            output_folder = arg
        elif opt in ("-s", "--site_id"):
            site_id = arg
        elif opt in ("-m", "--manual_id"):
            manual_id = arg
        elif opt in ("-a", "--article_id"):
            article_id = arg
        elif opt in ("-M", "--manual_file_name"):
            if manual_id != "":
                manual_file_name = arg
        elif opt in ("-i", "--object_identifier"):
            object_identifier = arg

    # check if required attributes exist
    if (site_name == '') or (user_id == '') or (api_token == ''):
        print("Site_name, user_id, and password are required. Try 'run -h' if you need help.")
        sys.exit()

    # if the output isn't specified, just put it in their home directory
    if (output_folder == ''):
        output_folder = os.path.expanduser('~')

    # if the template folder isn't specified, we'll just print out html files, otherwise we
    # have some prep work to do.
    if (template_folder == ''):
        template_specified = False
        is_article_folder = False
        is_manual_files = False
        is_image_folder = False
        is_attach_folder = False
        print("Warn: Template folder not specified.  Will output HTML files only.")
    else:
        # check if template folder exists
        if os.path.exists(template_folder):
            template_specified = True

            # check if folder has an @article folder
            at_article_folder = find_dirs("@article",template_folder)

            if len(at_article_folder) == 0:
                print("Info: No @article folder found.")
                is_article_folder = False
            elif len(at_article_folder) == 1:
                at_article_folder = at_article_folder[0]
                print("Info: Template folder has @article folder. "  + _decode(at_article_folder))
                is_article_folder = True
            else:
                print("Error: More than one @article folder found.")
                sys.exit()

            # check if folder has an @images folder
            at_images_folder = find_file(image_folder_indicator,template_folder)

            if len(at_images_folder) == 0:
                print("Info: No " + image_folder_indicator + " file found.")
                is_image_folder = False
            elif len(at_images_folder) == 1:
                at_images_folder = find_at_file_path(os.path.dirname(at_images_folder[0]),template_folder)
                print("Info: Template folder has " + image_folder_indicator + " file. "  + _print(at_images_folder))
                is_image_folder = True
            else:
                print("Error: More than one " + _print(image_folder_indicator) + " file found.")
                sys.exit()

            # check if folder has an @attachments folder
            at_attach_folder = find_file(attach_folder_indicator,template_folder)

            if len(at_attach_folder) == 0:
                print("Info: No " + attach_folder_indicator + " file found.")
                is_attach_folder = False
            elif len(at_attach_folder) == 1:
                at_attach_folder = find_at_file_path(os.path.dirname(at_attach_folder[0]),template_folder)
                print("Info: Template folder has " + attach_folder_indicator + " file. "  + _print(at_attach_folder))
                is_attach_folder = True
            else:
                print("Error: More than one " + attach_folder_indicator + " file found.")
                sys.exit()

            # now let's see if there are @article file(s). we'll take as many
            # as you want, as long as there is at least one!
            at_article_file = find_file(article_file_indicator,template_folder)

            if at_article_file == []:
                print("Error: No @article file found.")
                sys.exit()

            # ok, phew we found at least one
            else:
                print("Info: @article file(s) found.")

                # read in template data
                article_files = {}
                for each_article_file in at_article_file:
                    article_files[each_article_file] = read_file(each_article_file)

            # now let's check if theres a manual file
            at_manual_file = find_file(manual_file_indicator,template_folder)

            if at_manual_file == []:
                print("Warn: No @toc file found.")
                is_manual_files = False
            else:
                print("Info: @toc file(s) found.")
                is_manual_files = True

                # read in template data
                manual_files = {}
                manual_files_ref = {}

                for each_manual_file in at_manual_file:
                    manual_files[each_manual_file] = read_file(each_manual_file)

                    # Each @manual file consists of pre-chapter block, chapter block, and post-chapter block
                    # the chapter block then consists of the pre-article block, the article block, and post-article block
                    chapter_split = re.split('{{chapter}}',manual_files[each_manual_file])

                    if len(chapter_split) < 3:
                        chapter_split = ['',chapter_split[0],'']

                    article_split = re.split('{{article}}',chapter_split[1])

                    if len(article_split) < 3:
                        add_end_manual_file = article_split[0]
                        article_split = ['','','']
                    else:
                        add_end_manual_file = ''

                    manual_files_ref[each_manual_file] = [
                                                                chapter_split[0], # 0 - pre-chapter
                                                                article_split[0], # 1 - pre-article (chapter)
                                                                article_split[2], # 2 - article
                                                                article_split[3], # 3 - post-article (chapter)
                                                                chapter_split[2]] # 4 - post-chapter

        # template folder didn't exist
        else:
            print("Error: Template folder not found. Try 'run -h' if you need help.")
            sys.exit()

    # set up request
    def screensteps_json(endpoint):
        base_url = 'https://' + site_name + '.screenstepslive.com/api/v2/'
        site_endpoint = base_url + endpoint
        try:
            while True:
                r = requests.get(site_endpoint, auth=(user_id, api_token))

                if r.status_code == 200:
                    return r.text
                elif r.status_code == 429:
                    # Rate limit exceeded
                    try:
                        retry_info = r.json()
                        retry_in = retry_info.get('retry_in', 60)  # Default to 60 seconds if not provided
                        print(f"Rate limit exceeded. Retrying in {retry_in} seconds...")
                        time.sleep(retry_in)
                    except ValueError:
                        # Failed to parse JSON, fall back to a default wait time
                        print("Rate limit exceeded. Retrying in 60 seconds (default)...")
                        time.sleep(60)
                else:
                    print('Error connecting to server (' + _decode(r.status_code) + ')')
                    sys.exit(2)
        except requests.exceptions.RequestException as e:
            print("Error connecting to server:", e)
            sys.exit(2)

    def screensteps(endpoint):
        rawtext = screensteps_json(endpoint)
        return json.loads(rawtext)

    # grab all sites for that user information
    print("> Pulling sites")
    sites = screensteps('sites') # grab sites
    print("> " + _print(str(sites)))

    # loop through sites
    for site in sites['sites']:
        this_site_id = _decode(site['id'])
        if (site_id == this_site_id) or (site_id == ''): # only action a site if site_id isn't set, or is a match
            print(">> Processing site: " + _print(site['title']))
            # print(">> " + _print(site))

            # folder for site - two paths 1) template folder, 2) no template folder
            if object_identifier == "title_id":
                site_folder = os.path.join(output_folder, prepare_for_filename(site['title']) + " [" + this_site_id + "]")
            elif object_identifier == "title":
                site_folder = os.path.join(output_folder, prepare_for_filename(site['title']))
            else:
                site_folder = os.path.join(output_folder, this_site_id)

            if template_specified:
                copy_and_overwrite(template_folder, site_folder, incremental=incremental) # new code section
            else:
                make_dir(site_folder)

            manuals = screensteps('sites/' + this_site_id) #grab manuals

            # loop through manuals
            for manual in manuals['site']['manuals']:
                this_manual_id = _decode(manual['id'])
                if (manual_id == this_manual_id) or (manual_id == ''): # only action a manual if manual isn't set, or is a match
                    print(">>> Processing manual: " + _print(manual['title']))
                    # print(">>> " + _print(manual))

                    if object_identifier == "title_id":
                        this_manual_identifier = prepare_for_filename(manual["title"]) + " [" + this_manual_id + "]"
                    elif object_identifier == "title":
                        this_manual_identifier = prepare_for_filename(manual["title"])
                    else:
                        this_manual_identifier = this_manual_id

                    chapters = screensteps('sites/' + this_site_id + '/manuals/' + this_manual_id) # grab chapters

                    # pre-chapter replaces on _decode(manual_files_ref[path][0])
                    if is_manual_files: # are there templates?
                        manual_files_temp = {}
                        for path, details in manual_files.items():
                            manual_files_temp[path] = []
                            manual_files_temp[path].append(_decode(manual_files_ref[path][0]).replace('{{title}}', chapters['manual']['title']))

                    # loop through chapters
                    for chapter in chapters['manual']['chapters']:
                        this_chapter_id = _decode(chapter['id'])
                        print(">>>> Processing chapter: " + _print(chapter['title']))
                        # print(">>>> " + _print(chapter))

                        chapter['articles'] = []

                        # pre-article replaces on _decode(manual_files_ref[path][1])
                        if is_manual_files: # are there templates?
                            for path, details in manual_files.items():
                                manual_files_temp[path].append(_decode(manual_files_ref[path][1]).replace('{{title}}', chapter['title']))

                        articles = screensteps('sites/' + this_site_id + '/chapters/' + this_chapter_id) # grab articles

                        # loop through articles
                        for article in articles['chapter']['articles']:
                            this_article_id = _decode(article['id'])
                            if (article_id == this_article_id) or (article_id == ''): # only action an article if article_id isn't set, or is a match
                                print(">>>>> Processing article: " + _print(article['title']))
                                # print(">>>>> " + _print(article))

                                this_article = screensteps('sites/' + this_site_id + '/articles/' + this_article_id) # grab ind article

                                this_article_title = this_article['article']['title']
                                
                                # new code section: Calculate source modification time for incremental processing
                                this_article_mtime = get_source_mtime(this_article['article'].get('last_edited_at'))

                                if object_identifier == "title_id":
                                    this_article_identifier = prepare_for_filename(this_article_title) + " [" + this_article_id + "]"
                                elif object_identifier == "title":
                                    this_article_identifier = prepare_for_filename(this_article_title)
                                else:
                                    this_article_identifier = this_article_id

                                if is_article_folder:
                                    article_folder = os.path.join(site_folder, find_relative_path(at_article_folder,template_folder), this_article_identifier)
                                    copy_and_overwrite(at_article_folder, article_folder, incremental=incremental) # new code section
                                else:
                                    # write html to a file if no templates
                                    article_folder = site_folder

                                # Add to list of article ids and titles
                                chapter["articles"].append( {'id': this_article['article']['id'], 'title': this_article_identifier} )

                                article_html = this_article['article']['html_body']

                                # --- ADD HEADERS AND ORIGINAL CANONICAL LINKS TO TEXT STREAM ---
                                article_last_edited = _decode(this_article['article'].get('last_edited_at', ''))
                                custom_header_block = f"<h1>{this_article_title}</h1>\n<p>Modified Date: {article_last_edited}</p>\n<p>Original Article Link: <a href=\"https://{site_name}.screenstepslive.com/a/{this_article_id}\">https://{site_name}.screenstepslive.com/a/{this_article_id}</a></p>\n"
                                
                                # Prepend the new header blocks to the text layouts
                                article_html = custom_header_block + article_html

                                # loop through attached files
                                this_articles_files = []
                                for content_block in this_article['article']['content_blocks']:
                                    if 'url' in content_block:

                                        # what type of file is it?
                                        download_ext = os.path.splitext(urlparse(content_block['url']).path)[1]
                                        if content_block['type'] == 'AttachmentContent': # attachment
                                            if is_attach_folder:
                                                files_folder = os.path.join(site_folder,at_attach_folder)
                                                short_files_folder = at_attach_folder
                                                if '@article' in files_folder:
                                                    files_folder = files_folder.replace("@article", this_article_identifier)
                                                    short_files_folder = short_files_folder.replace("@article", this_article_identifier)
                                            else:
                                                files_folder = os.path.join(article_folder, 'attachments')
                                                short_files_folder = 'attachments'
                                                make_dir(files_folder)
                                        else: # image
                                            if is_image_folder:
                                                files_folder = os.path.join(site_folder,at_images_folder)
                                                short_files_folder = at_images_folder
                                                if '@article' in files_folder:
                                                    files_folder = files_folder.replace("@article", this_article_identifier)
                                                    short_files_folder = short_files_folder.replace("@article", this_article_identifier)
                                            else:
                                                files_folder = os.path.join(article_folder, 'images')
                                                short_files_folder = 'images'
                                                make_dir(files_folder)

                                        print(">>>>>> Processing " + _print(content_block['type']) + ": " + _print(content_block['url']))
                                        new_file_path = download_file(files_folder,content_block['url'], source_mtime=this_article_mtime, incremental=incremental) # new code section
                                        this_articles_files.append([ _decode(content_block['url']), os.path.join(short_files_folder,new_file_path)])

                                article_files_paths = []
                                if template_specified:
                                    # step through each file that starts with "@article"
                                    for path, temp_html in article_files.items():

                                        back_dir = ''
                                        article_relative_path = find_relative_path(path,template_folder)
                                        temp_filename = this_article_identifier + os.path.splitext(path)[1]
                                        if article_relative_path != '':
                                            article_relative_path = article_relative_path.replace("@article", this_article_identifier)
                                            temp_filename = os.path.join(article_relative_path,temp_filename)
                                            back_dir = '../' * len(split_path(article_relative_path))

                                        # find and replace {{html}}
                                        temp_towrite = temp_html.replace("""{{html}}""",article_html)
                                        temp_towrite = temp_towrite.replace("""{{json}}""",json.dumps(this_article, sort_keys=True, indent=2, separators=(',', ': ')))

                                        # find and replace all the other handlebars specified
                                        for article_handlebar in article_handlebars:
                                            if article_handlebar != "link":
                                                temp_towrite = temp_towrite.replace(("{{" + _decode(article_handlebar) + "}}"), _decode(this_article['article'][article_handlebar]) )

                                        for this_articles_file in this_articles_files:
                                            # take off any query params
                                            image_url = this_articles_file[0].split("?", 1)[0]
                                            temp_towrite = temp_towrite.replace(image_url,(back_dir + this_articles_file[1].replace("\\", "/"))) # Fix windows paths
                                            # workaround: perform replace on thumbnail images
                                            thumbnail_url = image_url.replace("/original/", "/medium/")
                                            temp_towrite = temp_towrite.replace(thumbnail_url,(back_dir + this_articles_file[1].replace("\\", "/"))) # Fix windows paths

                                        # write file
                                        write_file(site_folder, temp_filename, temp_towrite, source_mtime=this_article_mtime, incremental=incremental) # new code section
                                        article_files_paths.append(temp_filename)
                                else:
                                    for this_articles_file in this_articles_files:
                                        image_url = this_articles_file[0].split("?", 1)[0]
                                        local_path = this_articles_file[1].replace("\\", "/")
                                        
                                        # Replace the exact original URL (usually catches the href)
                                        article_html = article_html.replace(image_url, local_path) 
                                        
                                        # When not using a template catch and replace ScreenSteps resized images (catches the src) or theyll get skipped
                                        if "/original/" in image_url:
                                            article_html = article_html.replace(image_url.replace("/original/", "/medium/"), local_path)
                                            article_html = article_html.replace(image_url.replace("/original/", "/large/"), local_path)
                                            article_html = article_html.replace(image_url.replace("/original/", "/small/"), local_path)
                                            
                                    write_file(article_folder, (this_article_identifier + '.html'), article_html, source_mtime=this_article_mtime, incremental=incremental) # new code section
                                    article_files_paths.append((this_article_identifier + '.html'))

                                # article replaces on _decode(manual_files_ref[path][2])
                                if is_manual_files: # are there templates?
                                    article_handlebars.append("link")

                                    for path, details in manual_files.items():
                                        article_string = _decode(manual_files_ref[path][2])
                                        for article_handlebar in article_handlebars:
                                            if article_handlebar == "link":
                                                try:
                                                    same_ext_link = next(i for i in article_files_paths if os.path.splitext(i)[1] ==  os.path.splitext(path)[1])
                                                except:
                                                    print("Error: We didn't find a file extension match for the article from the TOC with: " + os.path.splitext(path)[1])
                                                    sys.exit()
                                                article_string = article_string.replace(("{{" + _decode(article_handlebar) + "}}"), same_ext_link)
                                            else:
                                                article_string = article_string.replace(("{{" + _decode(article_handlebar) + "}}"),_decode(this_article['article'][article_handlebar]))
                                        manual_files_temp[path].append(article_string)

                        # post-article replaces on _decode(manual_files_ref[path][3])
                        if is_manual_files: # are there templates?
                            for path, details in manual_files.items():
                                manual_files_temp[path].append(_decode(manual_files_ref[path][3]).replace('{{title}}',_decode(chapter['title'])))

                    # post-chapter replaces on _decode(manual_files_ref[path][4])
                    if is_manual_files: # are there templates?
                        for path, details in manual_files.items():
                            manual_files_temp[path].append(_decode(manual_files_ref[path][4]).replace('{{title}}',chapters['manual']['title']))

                            manual_relative_path = find_relative_path(path,template_folder)
                            if manual_relative_path == '':
                                manual_relative_path = site_folder
                            else:
                                manual_relative_path = os.path.join(site_folder,manual_relative_path)

                        # dump files
                        if manual_file_name != "":
                            temp_filename = manual_file_name + os.path.splitext(path)[1]
                        else:
                            temp_filename = this_manual_identifier + os.path.splitext(path)[1]
                        temp_file_contents = (''.join(manual_files_temp[path]) + add_end_manual_file)
                        temp_file_contents = temp_file_contents.replace("""{{json}}""", json.dumps(chapters, sort_keys=True, indent=2, separators=(',', ': ')))
                        write_file(manual_relative_path, temp_filename, temp_file_contents) # leaving without mtime as manual is dynamic compile

            if manual_id == '' and article_id == '':
                # new code section: Flag this folder as completely processed so ghost files can be swept safely
                FULLY_PROCESSED_FOLDERS.add(os.path.abspath(site_folder))

            # clean up the "@" files that we copied over for each site
            if template_specified:
                try:
                    remove_found_files(find_file(article_file_indicator,site_folder))
                    remove_found_files(find_file(manual_file_indicator,site_folder))
                    remove_found_files(find_file(image_folder_indicator,site_folder))
                    remove_found_files(find_file(attach_folder_indicator,site_folder))
                    remove_directories(find_dirs("@article", site_folder))
                except:
                    print("We had trouble deleting the copied template files.  You can ignore any extra files.")

    # new code section: Handle cleaning up "ghost" files that were in the directory but no longer exist in the API source
    if incremental:
        print("> Cleaning up deleted files...")
        for base_folder in FULLY_PROCESSED_FOLDERS:
            for root, dirs, files in os.walk(base_folder, topdown=False):
                for name in files:
                    file_path = os.path.abspath(os.path.join(root, name))
                    if os.path.exists(file_path) and file_path not in TRACKED_PATHS:
                        print(">>> Deleting obsolete file: " + file_path)
                        os.remove(file_path)
                for name in dirs:
                    dir_path = os.path.abspath(os.path.join(root, name))
                    if os.path.exists(dir_path) and dir_path not in TRACKED_PATHS:
                        try:
                            os.rmdir(dir_path)
                            print(">>> Deleting obsolete directory: " + dir_path)
                        except OSError:
                            pass

if __name__ == "__main__":
    main(sys.argv[1:])
