from itertools import count
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


class FakeSignal:
    def __init__(self):
        self._callbacks: List[Callable[..., Any]] = []

    @property
    def callback(self) -> Callable[..., Any]:
        if len(self._callbacks) != 1:
            raise AttributeError("Signal does not have exactly one connected callback")
        return self._callbacks[0]

    def connect(self, callback: Callable[..., Any]) -> None:
        if not callable(callback):
            raise TypeError("Signal callbacks must be callable")
        self._callbacks.append(callback)

    def emit(self, *args: Any, **kwargs: Any) -> None:
        for callback in tuple(self._callbacks):
            callback(*args, **kwargs)


class FakeAction:
    def __init__(self, icon: Any, text: str, parent: Any):
        self.icon = icon
        self._text = text
        self.parent = parent
        self.triggered = FakeSignal()
        self._status_tip = ""

    def text(self) -> str:
        return self._text

    def setStatusTip(self, status_tip: str) -> None:
        self._status_tip = status_tip

    def statusTip(self) -> str:
        return self._status_tip

    def trigger(self) -> None:
        self.triggered.emit()


class FakeMenu:
    def __init__(self, title: str, parent: Any):
        self._title = title
        self.parent = parent
        self._actions: List[FakeAction] = []
        self._menu_action = FakeAction(None, title, parent)

    def title(self) -> str:
        return self._title

    def addAction(self, action: FakeAction) -> FakeAction:
        if not isinstance(action, FakeAction):
            raise TypeError("FakeMenu.addAction expects a FakeAction")
        self._actions.append(action)
        return action

    def actions(self) -> List[FakeAction]:
        return list(self._actions)

    def menuAction(self) -> FakeAction:
        return self._menu_action


class FakeComboBox:
    def __init__(self):
        self._items: List[Tuple[str, Any]] = []
        self._current_index = -1
        self._enabled = True
        self._signals_blocked = False
        self.currentIndexChanged = FakeSignal()
        self.currentTextChanged = FakeSignal()

    def addItem(self, text: str, user_data: Any = None) -> None:
        self._items.append((str(text), user_data))
        if self._current_index == -1:
            self.setCurrentIndex(0)

    def addItems(self, texts: Sequence[str]) -> None:
        for text in texts:
            self.addItem(text)

    def clear(self) -> None:
        previous_index = self._current_index
        previous_text = self.currentText()
        self._items.clear()
        self._current_index = -1
        if previous_index != -1 and not self._signals_blocked:
            self.currentIndexChanged.emit(-1)
            if previous_text:
                self.currentTextChanged.emit("")

    def count(self) -> int:
        return len(self._items)

    def itemText(self, index: int) -> str:
        return self._items[index][0]

    def itemData(self, index: int) -> Any:
        return self._items[index][1]

    def currentIndex(self) -> int:
        return self._current_index

    def currentText(self) -> str:
        if self._current_index == -1:
            return ""
        return self._items[self._current_index][0]

    def currentData(self) -> Any:
        if self._current_index == -1:
            return None
        return self._items[self._current_index][1]

    def setCurrentIndex(self, index: int) -> None:
        if not isinstance(index, int):
            raise TypeError("Combo box index must be an integer")
        if index < -1 or index >= len(self._items):
            raise IndexError("Combo box index is outside the available items")
        if index == self._current_index:
            return

        previous_text = self.currentText()
        self._current_index = index
        current_text = self.currentText()
        if not self._signals_blocked:
            self.currentIndexChanged.emit(index)
            if current_text != previous_text:
                self.currentTextChanged.emit(current_text)

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self._enabled

    def blockSignals(self, blocked: bool) -> bool:
        previous = self._signals_blocked
        self._signals_blocked = bool(blocked)
        return previous


class FakeMessageBar:
    def __init__(self):
        self.messages: List[Tuple[str, str, str]] = []

    @property
    def success_messages(self) -> List[Tuple[str, str]]:
        return [(title, text) for level, title, text in self.messages if level == "success"]

    @property
    def warning_messages(self) -> List[Tuple[str, str]]:
        return [(title, text) for level, title, text in self.messages if level == "warning"]

    def pushSuccess(self, title: str, text: str) -> None:
        self.messages.append(("success", title, text))

    def pushWarning(self, title: str, text: str) -> None:
        self.messages.append(("warning", title, text))

    def pushCritical(self, title: str, text: str) -> None:
        self.messages.append(("critical", title, text))

    def pushInfo(self, title: str, text: str) -> None:
        self.messages.append(("info", title, text))


class FakeMapCanvas:
    def __init__(self):
        self._event_filters: List[Any] = []
        self.refresh_count = 0

    def viewport(self):
        return self

    def installEventFilter(self, event_filter: Any) -> None:
        self._event_filters.append(event_filter)

    def removeEventFilter(self, event_filter: Any) -> None:
        if event_filter in self._event_filters:
            self._event_filters.remove(event_filter)

    def refresh(self) -> None:
        self.refresh_count += 1


class FakeQgisInterface:
    def __init__(self, active_layer: Any = None):
        self._active_layer = active_layer
        self._main_window = object()
        self._map_canvas = FakeMapCanvas()
        self._message_bar = FakeMessageBar()
        self.menu_additions: List[Tuple[str, Any]] = []
        self.menu_removals: List[Tuple[str, Any]] = []
        self.toolbar_additions: List[Any] = []
        self.toolbar_removals: List[Any] = []

    def mainWindow(self):
        return self._main_window

    def activeLayer(self):
        return self._active_layer

    def setActiveLayer(self, layer: Any) -> None:
        self._active_layer = layer

    def mapCanvas(self) -> FakeMapCanvas:
        return self._map_canvas

    def messageBar(self) -> FakeMessageBar:
        return self._message_bar

    def addPluginToMenu(self, menu_name: str, action: Any) -> None:
        self.menu_additions.append((menu_name, action))

    def removePluginMenu(self, menu_name: str, action: Any) -> None:
        self.menu_removals.append((menu_name, action))

    def addToolBarIcon(self, action: Any) -> None:
        self.toolbar_additions.append(action)

    def removeToolBarIcon(self, action: Any) -> None:
        self.toolbar_removals.append(action)


class FakeField:
    def __init__(self, name: str, field_type: Any = None):
        self._name = name
        self.field_type = field_type

    def name(self) -> str:
        return self._name


class FakePoint:
    def __init__(self, x: float, y: float):
        self._x = float(x)
        self._y = float(y)

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y


class FakeCRS:
    def __init__(self, authid: str = "EPSG:4326", valid: bool = True):
        self._authid = authid
        self._valid = valid

    def authid(self) -> str:
        return self._authid

    def isValid(self) -> bool:
        return self._valid


class FakeGeometry:
    def __init__(
        self,
        geometry_type: str,
        parts: Sequence[Sequence[FakePoint]],
        empty: bool = False,
        multipart: Optional[bool] = None,
    ):
        self._geometry_type = geometry_type
        self._parts = [list(part) for part in parts]
        self._empty = empty or not any(self._parts)
        self._multipart = len(self._parts) > 1 if multipart is None else multipart

    @classmethod
    def from_points(cls, coordinates: Sequence[Tuple[float, float]]):
        points = [FakePoint(x, y) for x, y in coordinates]
        return cls("point", [[point] for point in points], multipart=len(points) > 1)

    @classmethod
    def fromPointXY(cls, point: FakePoint):
        return cls("point", [[point]], multipart=False)

    @classmethod
    def fromPolylineXY(cls, points: Sequence[FakePoint]):
        return cls("line", [list(points)] if points else [], multipart=False)

    @classmethod
    def from_polyline(cls, coordinates: Sequence[Tuple[float, float]]):
        points = [FakePoint(x, y) for x, y in coordinates]
        return cls("line", [points] if points else [], multipart=False)

    @classmethod
    def from_multipolyline(
        cls,
        lines: Sequence[Sequence[Tuple[float, float]]],
    ):
        parts = [
            [FakePoint(x, y) for x, y in line]
            for line in lines
        ]
        return cls("line", parts, multipart=True)

    @classmethod
    def empty(cls, geometry_type: str = "point"):
        return cls(geometry_type, [], empty=True, multipart=False)

    def isEmpty(self) -> bool:
        return self._empty

    def isMultipart(self) -> bool:
        return self._multipart

    def asPoint(self) -> Optional[FakePoint]:
        if self._geometry_type != "point" or self._multipart or not self._parts:
            return None
        return self._parts[0][0] if self._parts[0] else None

    def asMultiPoint(self) -> List[FakePoint]:
        if self._geometry_type != "point":
            return []
        return [point for part in self._parts for point in part]

    def asPolyline(self) -> List[FakePoint]:
        if self._geometry_type != "line" or self._multipart or not self._parts:
            return []
        return list(self._parts[0])

    def asMultiPolyline(self) -> List[List[FakePoint]]:
        if self._geometry_type != "line":
            return []
        return [list(part) for part in self._parts]


class FakeFeature:
    def __init__(
        self,
        attributes: Any = None,
        geometry: Optional[FakeGeometry] = None,
        feature_id: int = 1,
    ):
        if attributes is None:
            fields = []
            self._attributes = {}
        elif isinstance(attributes, dict):
            fields = []
            self._attributes = dict(attributes)
        else:
            fields = list(attributes)
            self._attributes = {}
        self._geometry = geometry
        self._feature_id = feature_id
        self._fields = fields
        self._pending_attributes = None

    def id(self) -> int:
        return self._feature_id

    def geometry(self) -> Optional[FakeGeometry]:
        return self._geometry

    def setGeometry(self, geometry: FakeGeometry) -> None:
        if not isinstance(geometry, FakeGeometry):
            raise TypeError("FakeFeature.setGeometry expects a FakeGeometry")
        self._geometry = geometry

    def setAttributes(self, values: Sequence[Any]) -> None:
        if self._fields:
            self._attributes = {
                field.name(): value
                for field, value in zip(self._fields, values)
            }
            return
        self._pending_attributes = list(values)

    def _bind_fields(self, fields: Sequence[FakeField]) -> None:
        self._fields = list(fields)
        if self._pending_attributes is not None:
            self._attributes = {
                field.name(): value
                for field, value in zip(self._fields, self._pending_attributes)
            }
            self._pending_attributes = None

    def __getitem__(self, field_name: str) -> Any:
        return self._attributes[field_name]


_layer_ids = count(1)


class FakeVectorLayer:
    def __init__(
        self,
        name: str,
        fields: Sequence[FakeField],
        features: Sequence[FakeFeature] = (),
        layer_type: Any = None,
        geometry_type: Any = None,
        crs: Optional[FakeCRS] = None,
    ):
        self._name = name
        self._fields = list(fields)
        self._features = list(features)
        self._layer_type = layer_type
        self._geometry_type = geometry_type
        self._crs = crs or FakeCRS()
        self._id = f"fake-layer-{next(_layer_ids)}"
        self.get_features_calls = 0

    def id(self) -> str:
        return self._id

    def name(self) -> str:
        return self._name

    def type(self):
        return self._layer_type

    def geometryType(self):
        return self._geometry_type

    def fields(self) -> List[FakeField]:
        return list(self._fields)

    def getFeatures(self):
        self.get_features_calls += 1
        return iter(self._features)

    def addFeature(self, feature: FakeFeature) -> None:
        if not isinstance(feature, FakeFeature):
            raise TypeError("FakeVectorLayer.addFeature expects a FakeFeature")
        self._features.append(feature)

    def crs(self) -> FakeCRS:
        return self._crs

    def featureCount(self) -> int:
        return len(self._features)

    def isValid(self) -> bool:
        return True

    def updateFields(self) -> None:
        pass

    def updateExtents(self) -> None:
        pass


class FakeVectorDataProvider:
    def __init__(self, layer: "FakeMemoryVectorLayer"):
        self._layer = layer

    def addAttributes(self, fields: Sequence[FakeField]) -> bool:
        if not all(isinstance(field, FakeField) for field in fields):
            raise TypeError("FakeVectorDataProvider expects FakeField instances")
        self._layer._fields.extend(fields)
        return True

    def addFeature(self, feature: FakeFeature) -> bool:
        return self.addFeatures([feature])

    def addFeatures(self, features: Sequence[FakeFeature]) -> bool:
        for feature in features:
            if not isinstance(feature, FakeFeature):
                raise TypeError("FakeVectorDataProvider expects FakeFeature instances")
            feature._bind_fields(self._layer._fields)
            self._layer.addFeature(feature)
        return True


class FakeMemoryVectorLayer(FakeVectorLayer):
    def __init__(
        self,
        uri: str,
        name: str,
        provider: str,
        layer_type: Any,
        point_geometry_type: Any,
        line_geometry_type: Any,
    ):
        geometry_name = uri.partition("?")[0].lower()
        if geometry_name == "point":
            geometry_type = point_geometry_type
        elif geometry_name == "linestring":
            geometry_type = line_geometry_type
        else:
            raise ValueError(f"Unsupported fake memory-layer geometry: {geometry_name}")

        super().__init__(
            name,
            [],
            layer_type=layer_type,
            geometry_type=geometry_type,
        )
        self.uri = uri
        self.provider = provider
        self._data_provider = FakeVectorDataProvider(self)

    def dataProvider(self) -> FakeVectorDataProvider:
        return self._data_provider


class FakeQgsProject:
    _instance = None

    def __init__(self):
        self._layers: Dict[str, Any] = {}

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def addMapLayer(self, layer: Any, addToLegend: bool = True):
        self._layers[layer.id()] = layer
        return layer

    def addMapLayers(self, layers: Sequence[Any], addToLegend: bool = True):
        return [self.addMapLayer(layer, addToLegend) for layer in layers]

    def mapLayers(self) -> Dict[str, Any]:
        return dict(self._layers)

    def removeMapLayer(self, layer_or_id: Any) -> None:
        layer_id = layer_or_id if isinstance(layer_or_id, str) else layer_or_id.id()
        self._layers.pop(layer_id, None)
