FROM nginx:alpine
COPY frontend/ /usr/share/nginx/html/
COPY output/ /usr/share/nginx/html/output/
