FROM searxng/searxng:latest

# Custom Wave Search settings (theme=simple, dark, Wave OS engine list).
COPY searxng-settings.yml /etc/searxng/settings.yml

# Wave OS dark skin + rebrand script (applied to the stock "simple" theme).
COPY wave-dark.css /tmp/wave-dark.css
COPY rebrand.sh /tmp/rebrand.sh
RUN sh /tmp/rebrand.sh

EXPOSE 8080

CMD ["uwsgi", "--http", "0.0.0.0:8080", "--wsgi-file", "searx/webapp.py", "--master", "--processes", "4", "--threads", "2"]
