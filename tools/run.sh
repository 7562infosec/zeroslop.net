#!/usr/bin/env bash
#
# Run jekyll serve and then launch the site

prod=false
host="127.0.0.1"

help() {
  echo "Usage:"
  echo
  echo "   bash /path/to/run [options]"
  echo
  echo "Options:"
  echo "     -H, --host [HOST]    Host to bind to."
  echo "     -p, --production     Run Jekyll in 'production' mode."
  echo "     -h, --help           Print this help information."
}

while (($#)); do
  opt="$1"
  case $opt in
  -H | --host)
    host="$2"
    shift 2
    ;;
  -p | --production)
    prod=true
    shift
    ;;
  -h | --help)
    help
    exit 0
    ;;
  *)
    echo -e "> Unknown option: '$opt'\n"
    help
    exit 1
    ;;
  esac
done

# Validate host is a safe hostname/IP
if [[ ! "$host" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    echo "Error: invalid host argument"
    exit 1
fi

# Build jekyll args as array (no eval)
jekyll_args=(exec jekyll s -l -H "$host")

if $prod; then
  export JEKYLL_ENV=production
fi

if [ -e /proc/1/cgroup ] && grep -q docker /proc/1/cgroup; then
  jekyll_args+=("--force_polling")
fi

echo -e "\n> bundle ${jekyll_args[*]}\n"
bundle "${jekyll_args[@]}"