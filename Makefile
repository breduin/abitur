.PHONY: run stop rerun logs build migrate makemigrations shell test createsuperuser

run:
	docker compose up -d --build

stop:
	docker compose down

rerun: stop run

logs:
	docker compose logs -f

build:
	docker compose build

migrate:
	docker compose exec web python manage.py migrate

makemigrations:
	docker compose exec web python manage.py makemigrations $(app)

shell:
	docker compose exec web python manage.py shell

test:
	docker compose exec web python manage.py test

createsuperuser:
	docker compose exec web python manage.py createsuperuser
