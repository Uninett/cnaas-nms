FROM debian:buster
ARG BUILDBRANCH=develop

# Create directories
RUN mkdir -p /opt/cnaas/templates/ /opt/cnaas/settings/ /opt/cnaas/static/ /etc/cnaas-nms/

# Copy configuration files
COPY config/db_config.yml config/api.yml config/repository.yml config/plugins.yml \
     /etc/cnaas-nms/

# Setup script
COPY cnaas-setup.sh /opt/cnaas/
RUN /opt/cnaas/cnaas-setup.sh $BUILDBRANCH

# Prepare for supervisord, uwsgi, ngninx
COPY nosetests.sh exec-pre-app.sh /opt/cnaas/
COPY --chown=root:www-data config/uwsgi.ini /opt/cnaas/venv/cnaas-nms/
COPY config/supervisord_app.conf /etc/supervisor/supervisord.conf
COPY config/nginx_app.conf /etc/nginx/sites-available/
COPY config/nginx.conf /etc/nginx/
COPY cert/cnaas_snakeoil.crt cert/cnaas_snakeoil.key /etc/nginx/conf.d/

# Websocket test client
COPY client.html /opt/cnaas/static/

# Give nginx some special treatment
RUN unlink /etc/nginx/sites-enabled/default
RUN ln -s /etc/nginx/sites-available/nginx_app.conf /etc/nginx/sites-enabled/default
RUN chown www-data:www-data /etc/cnaas-nms/*.yml
RUN chown -R www-data:www-data /var/log/nginx/ /var/lib/nginx/
RUN chown -R root:www-data /etc/nginx/ && \
    chmod -R u=rwX,g=rX,o= /etc/nginx/
# Give permission for API to clone/sync repos
RUN chown -R root:www-data /opt/cnaas/ && \
    chmod -R u=rwX,g=rX,o= /opt/cnaas/
RUN chown -R www-data:www-data /opt/cnaas/templates/ /opt/cnaas/settings/
# Give permission for unittests
RUN chown root:www-data /opt/cnaas/nosetests.sh && \
    chmod g+rx /opt/cnaas/nosetests.sh
RUN chown -R www-data:www-data /opt/cnaas/venv/cnaas-nms/src/


# Expose HTTPS
EXPOSE 1443

ENTRYPOINT supervisord -c /etc/supervisor/supervisord.conf
