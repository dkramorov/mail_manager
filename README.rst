Описание
-----------
Менеджер для работы с почтой

Установка пакетом
-----------
Для локальной разработки::
    pip install -e packages/mail_manager
Для обычной установки через requirements.txt::
    mail_manager @ git+https://github.com/dkramorov/mail_manager.git


Импорт
-----------
Проверка::
    from managers.mail_manager import MailProvider


Удаление
-----------
Удалить пакет::
    pip uninstall mail_manager

Для создания пакета
https://docs.python.org/3.10/distutils/introduction.html#distutils-simple-example
https://docs.python.org/3.10/distutils/sourcedist.html
::
    python setup.py sdist




