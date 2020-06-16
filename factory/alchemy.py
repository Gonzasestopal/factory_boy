# Copyright: See the LICENSE file.

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from . import base, errors

SESSION_PERSISTENCE_COMMIT = 'commit'
SESSION_PERSISTENCE_FLUSH = 'flush'
VALID_SESSION_PERSISTENCE_TYPES = [
    None,
    SESSION_PERSISTENCE_COMMIT,
    SESSION_PERSISTENCE_FLUSH,
]


class SQLAlchemyOptions(base.FactoryOptions):
    def _check_sqlalchemy_session_persistence(self, meta, value):
        if value not in VALID_SESSION_PERSISTENCE_TYPES:
            raise TypeError(
                "%s.sqlalchemy_session_persistence must be one of %s, got %r" %
                (meta, VALID_SESSION_PERSISTENCE_TYPES, value)
            )

    def _build_default_options(self):
        return super()._build_default_options() + [
            base.OptionDefault('sqlalchemy_get_or_create', (), inherit=True),
            base.OptionDefault('sqlalchemy_session', None, inherit=True),
            base.OptionDefault(
                'sqlalchemy_session_persistence',
                None,
                inherit=True,
                checker=self._check_sqlalchemy_session_persistence,
            ),
        ]


class SQLAlchemyModelFactory(base.Factory):
    """Factory for SQLAlchemy models. """

    _options_class = SQLAlchemyOptions

    class Meta:
        abstract = True

    @classmethod
    def _generate(cls, strategy, params):
        # Original params are used in _get_or_create if it cannot build an
        # object initially due to an IntegrityError being raised
        cls._original_params = params
        return super(SQLAlchemyModelFactory, cls)._generate(strategy, params)

    @classmethod
    def _get_or_create(cls, model_class, *args, **kwargs):
        """Get or create an instance of the model."""

        session = cls._meta.sqlalchemy_session

        key_fields = {}
        for field in cls._meta.sqlalchemy_get_or_create:
            if field not in kwargs:
                raise errors.FactoryError(
                    "sqlalchemy_get_or_create - "
                    "Unable to find initialization value for '%s' in factory %s" %
                    (field, cls.__name__))
            key_fields[field] = kwargs.pop(field)

        instance = session.query(model_class).filter_by(
            *args, **key_fields).one_or_none()

        try:
            if not instance:
                instance = model_class(*args, **key_fields)
                session.add(instance)
        except IntegrityError as e:
            session.rollback()
            get_or_create_params = {
                lookup: value
                for lookup, value in cls._original_params.items()
                if lookup in cls._meta.sqlalchemy_get_or_create
            }
            if get_or_create_params:
                try:
                    instance = session.query(model_class).filter_by(
                        **get_or_create_params).one()
                except NoResultFound:
                    # Original params are not a valid lookup and triggered a create(),
                    # that resulted in an IntegrityError. Follow SQLAlchemy´s behavior.
                    raise e
            else:
                raise e

        return instance

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Create an instance of the model, and save it to the database."""
        session = cls._meta.sqlalchemy_session
        session_persistence = cls._meta.sqlalchemy_session_persistence

        obj = model_class(*args, **kwargs)
        if session is None:
            raise RuntimeError("No session provided.")
        if cls._meta.sqlalchemy_get_or_create:
            obj = cls._get_or_create(model_class, *args, **kwargs)
        if obj not in session:
            session.add(obj)
        if session_persistence == SESSION_PERSISTENCE_FLUSH:
            session.flush()
        elif session_persistence == SESSION_PERSISTENCE_COMMIT:
            session.commit()
        return obj
