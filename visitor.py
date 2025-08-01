# type: ignore
import abc
from functools import wraps
import inspect
import typing


# Decorator to define abstract methods
def abstractmethod(f):
    @wraps(f)
    @abc.abstractmethod
    def inner():
        raise NotImplementedError(f"Calling non-implemented abstract method {f.__name__}")

    return inner


# Decorator to mark a method as an override
def overrides(f):
    f.__overrides__ = True
    return f


all_visitors = {}
visitprefix = "visit"


# Metaclass for abstract classes
class AbstractClassMeta(abc.ABCMeta):
    # Customize the creation of a new class
    def __new__(mcls, clsname, bases, attrs, **kwargs):
        cls = super().__new__(mcls, clsname, bases, attrs, **kwargs)

        # Find and store overridden methods
        overrided = {name for name, value in attrs.items() if getattr(value, "__overrides__", False)}
        overridable = set(cls.__abstractmethods__)
        for base in bases:
            overridable |= getattr(base, "__overridable__", set())

        cls.__overrided__ = frozenset(overrided)
        cls.__overridable__ = frozenset(overridable)

        # Save custom __new__
        if "__new__" in cls.__dict__:
            cls.__old__ = cls.__new__
        else:
            cls.__old__ = None

        AbstractClassMeta.update_new(cls)
        return cls

    # Static method to update overridden methods in a class
    @staticmethod
    def update_override(cls):
        abc.update_abstractmethods(cls)
        overrided = {name for name, value in cls.__dict__.items() if getattr(value, "__overrides__", False)}
        overridable = set(cls.__abstractmethods__)
        for base in cls.__bases__:
            overridable |= getattr(base, "__overridable__", set())

        # If there are changes in overridden or overridable methods, update the class and its subclasses
        if overridable != cls.__overridable__ or overrided != cls.__overrided__:
            cls.__overrided__ = frozenset(overrided)
            cls.__overridable__ = frozenset(overridable)
            AbstractClassMeta.update_new(cls)
            for sub in cls.__subclasses__():
                AbstractClassMeta.update_override(sub)

    # Static method to check if a class can be instantiated
    @staticmethod
    def can_instantiate(cls):
        return cls.__overrided__.issubset(cls.__overridable__)

    # Static method to raise an error if instantiation fails
    @staticmethod
    def fail(cls):
        incorrect_override = list(cls.__overrided__ - cls.__overridable__)
        if len(incorrect_override) == 0:
            raise RuntimeError("Fails, but should not fail")

        # Find the location of the function that is marked with @override
        first = getattr(cls, incorrect_override[0])
        file = inspect.getfile(first)
        line = inspect.getsourcelines(first)[1]
        location = f"File {file}, line {line}"

        if len(incorrect_override) == 1:
            raise TypeError(
                f"{location}\n{incorrect_override[0]} of {cls} is marked as @override, but does not override an abstract method"
            )
        else:
            raise TypeError(
                f"{location}\n{', '.join(incorrect_override[:-1])} and {incorrect_override[-1]} of {cls} are marked as @override, but do not override an abstract method"
            )

    # Static method to update the '__new__' method of a class
    @staticmethod
    def update_new(cls):
        # If instantiation is not possible, set '__new__' to the 'fail' method
        if not AbstractClassMeta.can_instantiate(cls):
            cls.__new__ = AbstractClassMeta.fail
        # Restore the original '__new__' method
        elif "__new__" in cls.__dict__:
            if cls.__old__ is not None:
                cls.__new__ = cls.__old__
            else:
                del cls.__new__


class VisitableMeta(AbstractClassMeta):
    def __new__(mcls, clsname, bases, attrs: dict, *, visitable=None, **kwargs):
        # Define an appropriate 'accept' method for the visitable class
        def accept(self, visitor, *args, **kwargs):
            f = getattr(visitor, f"visit{clsname}", None)
            if f is not None:
                return f(self, *args, **kwargs)
            raise TypeError(f"{type(visitor).__name__} is not a {clsname}Visitor")

        attrs["accept"] = accept

        # Create the visitable class using the superclass's __new__ method
        cls = super().__new__(mcls, clsname, bases, attrs, **kwargs)

        # Create a visitor class for the current visitable class
        all_visitors[cls] = AbstractClassMeta(f"{clsname}Visitor", (), {})

        if len(cls.__abstractmethods__) != 0 or visitable is False:
            return cls

        # Add corresponding visit functions in visitor class if this class is concrete
        visitName = f"visit{clsname}"
        for base in inspect.getmro(cls):
            if isinstance(base, VisitableMeta):
                basevisitor = all_visitors[base]

                # Define an abstract visit method for the visitor class
                @abstractmethod
                def visitChild(self, child):
                    pass

                visitChild.__name__ = visitName
                setattr(basevisitor, visitName, visitChild)

                # Make sure the addded method is abstract and subclasses know this
                AbstractClassMeta.update_override(basevisitor)

        return cls


class Visitable(metaclass=VisitableMeta):
    pass


def _getVisitMethod(name, scope, prefix, Visitor, method=False):
    if name[: len(visitprefix)] != visitprefix:
        raise AttributeError(name)
    if not hasattr(Visitor, name):
        raise AttributeError(name)
    suffix = name[len(visitprefix) :]
    delegate = scope.get(f"{prefix}{suffix}", None)
    if delegate is None:
        raise AttributeError(name)
    if method:
        return delegate
    return lambda self, *args, **kwargs: delegate(*args, **kwargs)


def visitor(t, prefix=visitprefix):
    if inspect.isfunction(t):
        return _functionVisitor(t)
    T = typing.TypeVar("T", bound=type)

    def removeSpecialAttributes(attrs):
        for special in ["__overridable__", "__overrided__", "__abstractmethods__"]:
            if special in attrs:
                del attrs[special]
        if "__old__" in attrs:
            if attrs["__old__"] is None:
                if "__new__" in attrs:
                    del attrs["__new__"]
                else:
                    attrs["__new__"] = attrs["__old__"]
                del attrs["__old__"]

    def inner(cls: T) -> T:
        # Recreate cls as a new class inheriting from the generated visitor class
        attrs = dict(cls.__dict__)
        removeSpecialAttributes(attrs)
        attrs[prefix] = lambda self, v, *args, **kwargs: v.accept(self, *args, **kwargs)
        Visitor = all_visitors[t]
        if prefix != visitprefix:
            for name in Visitor.__dict__:
                if name[: len(visitprefix)] != visitprefix:
                    continue
                try:
                    attrs[name] = _getVisitMethod(name, attrs, prefix, Visitor, True)
                except AttributeError:
                    raise NameError(
                        f"Cannot instantiate visitor {cls.__name__} because of missing {prefix}{name[len(visitprefix):]}"
                    )
        bases = (base for base in cls.__bases__ if not isinstance(Visitor, base))
        meta = AbstractClassMeta
        if isinstance(cls, AbstractClassMeta):
            meta = type(cls)
        return typing.cast(T, meta(cls.__name__, (*bases, Visitor), attrs))

    return inner


all_instantiators = []


def _functionVisitor(f):
    scope = inspect.currentframe().f_back.f_back.f_globals
    sig = iter(inspect.signature(f).parameters.values())
    first = next(sig)
    visited = first.annotation
    visitedname = visited.__name__
    functionname = f.__name__
    if functionname[-len(visitedname) :] == visitedname:
        functionname = functionname[: -len(visitedname)]
    Visitor = all_visitors[visited]

    @visitor(visited)
    class Impl:
        pass

    impl = None

    def instantiate(weak=False):
        nonlocal impl
        if impl is None:
            found = 0
            lasterror = None
            for name in Visitor.__dict__:
                if name[: len(visitprefix)] != visitprefix:
                    continue
                try:
                    setattr(Impl, name, _getVisitMethod(name, scope, functionname, Visitor))
                    found += 1
                except AttributeError:
                    file = inspect.getfile(f)
                    line = inspect.getsourcelines(f)[1]
                    location = f"File {file}, line {line}"
                    lasterror = NameError(
                        f"{location}\nCannot instantiate visitor {f.__name__} because of missing {functionname}{name[len(visitprefix):]}"
                    )
                    if not weak:
                        raise lasterror from None
            if found == 0 and weak:
                return
            if lasterror is not None:
                raise lasterror
            AbstractClassMeta.update_override(Impl)
            impl = Impl()

    def inner(v, *args, **kwargs):
        instantiate()
        return v.accept(impl, *args, **kwargs)

    inner.instantiate = instantiate
    instantiate(True)
    all_instantiators.append(instantiate)
    return inner


def instantiate_all_visitors():
    for instantiate in all_instantiators:
        instantiate()
