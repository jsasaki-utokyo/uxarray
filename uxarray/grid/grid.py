"""uxarray.core.grid module."""
import xarray as xr
import numpy as np

# reader and writer imports
from uxarray.io._exodus import _read_exodus, _encode_exodus
from uxarray.io._mpas import _read_mpas
from uxarray.io._ugrid import _read_ugrid, _encode_ugrid
from uxarray.io._shapefile import _read_shpfile
from uxarray.io._scrip import _read_scrip, _encode_scrip
from uxarray.io._connectivity import _read_face_vertices

from uxarray.io.utils import _parse_grid_type
from uxarray.grid.area import get_all_face_area_from_coords
from uxarray.grid.connectivity import (_build_edge_node_connectivity,
                                       _build_face_edges_connectivity,
                                       _build_nNodes_per_face)

from uxarray.grid.coordinates import (_populate_lonlat_coord,
                                      _populate_cartesian_xyz_coord)

from uxarray.constants import INT_DTYPE, INT_FILL_VALUE

from uxarray.grid.geometry import (_build_polygon_shells,
                                   _build_corrected_polygon_shells,
                                   _build_antimeridian_face_indices,
                                   _grid_to_polygon_geodataframe,
                                   _grid_to_matplotlib_polycollection,
                                   _grid_to_polygons)


class Grid:
    """Unstructured grid topology definition.

    Can be used standalone to explore an unstructured grid topology, or
    can be seen as the property of ``uxarray.UxDataset`` and ``uxarray.DataArray``
    to make them unstructured grid-aware data sets and arrays.

    Parameters
    ----------
    input_obj : xarray.Dataset, ndarray, list, tuple, required
        Input ``xarray.Dataset`` or vertex coordinates that form faces.

    Other Parameters
    ----------------
    gridspec: bool, optional
        Specifies gridspec
    islatlon : bool, optional
        Specify if the grid is lat/lon based
    isconcave: bool, optional
        Specify if this grid has concave elements (internal checks for this are possible)
    use_dual: bool, optional
        Specify whether to use the primal (use_dual=False) or dual (use_dual=True) mesh if the file type is mpas

    Raises
    ------
        RuntimeError
            If specified file not found or recognized

    Examples
    ----------

    >>> import uxarray as ux

    1. Open a grid file with `uxarray.open_grid()`:

    >>> uxgrid = ux.open_grid("filename.g")

    2. Open an unstructured grid dataset file with
    `uxarray.open_dataset()`, then access `Grid` info:

    >>> uxds = ux.open_dataset("filename.g")
    """

    def __init__(self, grid_ds, grid_spec, ugrid_mapping=None, **kwargs):

        # TODO: streamlined approach
        self._ugrid_mapping = ugrid_mapping

        # initialize face_area variable
        self._face_areas = None

        # initialize attributes
        self._antimeridian_face_indices = None

        # initialize cached data structures
        self._gdf = None
        self._poly_collection = None

        # internal xarray dataset for storing grid variables
        self._ds = grid_ds

        # source grid specification
        self.grid_spec = grid_spec

        # TODO: Still need?
        # # {"Standardized Name" : "Original Name"}
        # self._inverse_grid_var_names = {
        #     v: k for k, v in self.grid_var_names.items()
        # }

    @classmethod
    def from_dataset(cls, dataset, use_dual=False):
        if not isinstance(dataset, xr.Dataset):
            # TODO: Error Message
            raise ValueError

        # determine grid/mesh specification
        grid_spec = _parse_grid_type(dataset)

        if grid_spec == "Exodus":
            grid_ds, ugrid_mapping = _read_exodus(dataset)
        elif grid_spec == "Scrip":
            grid_ds, ugrid_mapping = _read_scrip(dataset)
        elif grid_spec == "UGRID":
            grid_ds, ugrid_mapping = _read_ugrid(dataset)
        elif grid_spec == "MPAS":
            grid_ds, ugrid_mapping = _read_mpas(dataset, use_dual=use_dual)
        elif grid_spec == "Shapefile":
            # TODO: Not supported, add appropriate exception
            raise ValueError
        else:
            pass

        return cls(grid_ds, grid_spec, ugrid_mapping)

    @classmethod
    def from_face_vertices(cls, face_vertices, latlon=True):
        """TODO: Better Name & Docstring"""
        if not isinstance(face_vertices, (list, tuple, np.ndarray)):
            # TODO: Error Message
            raise ValueError

        face_vertices = np.asarray(face_vertices)

        if face_vertices.ndim == 3:
            grid_ds = _read_face_vertices(face_vertices, latlon)

        elif face_vertices.ndim == 2:
            grid_ds = _read_face_vertices(np.array([face_vertices]), latlon)

        else:
            raise RuntimeError(
                f"Invalid Input Dimension: {face_vertices.ndim}. Expected dimension should be "
                f"3: [nMesh2_face, nMesh2_node, Two/Three] or 2 when only "
                f"one face is passed in.")

        return cls(grid_ds, grid_spec="Face Vertices")

    def __repr__(self):
        """Constructs a string representation of the contents of a ``Grid``."""
        # TODO: Make work without grid var names

        prefix = "<uxarray.Grid>\n"
        original_grid_str = f"Original Grid Type: {self.grid_spec}\n"
        dims_heading = "Grid Dimensions:\n"
        dims_str = ""
        # if self.grid_var_names["Mesh2_node_x"] in self._ds:
        #     dims_str += f"  * nMesh2_node: {self.nMesh2_node}\n"
        # if self.grid_var_names["Mesh2_face_nodes"] in self._ds:
        #     dims_str += f"  * nMesh2_face: {self.nMesh2_face}\n"
        #     dims_str += f"  * nMesh2_face: {self.nMesh2_face}\n"

        for key, value in zip(self._ds.dims.keys(), self._ds.dims.values()):
            if key in self._inverse_grid_var_names:
                dims_str += f"  * {self._inverse_grid_var_names[key]}: {value}\n"

        if "nMesh2_edge" in self._ds.dims:
            dims_str += f"  * nMesh2_edge: {self.nMesh2_edge}\n"

        if "nMaxMesh2_face_edges" in self._ds.dims:
            dims_str += f"  * nMaxMesh2_face_edges: {self.nMaxMesh2_face_edges}\n"

        coord_heading = "Grid Coordinate Variables:\n"
        coords_str = ""
        if "Mesh2_node_x" in self._ds:
            coords_str += f"  * Mesh2_node_x: {self.Mesh2_node_x.shape}\n"
            coords_str += f"  * Mesh2_node_y: {self.Mesh2_node_y.shape}\n"
        if "Mesh2_node_cart_x" in self._ds:
            coords_str += f"  * Mesh2_node_cart_x: {self.Mesh2_node_cart_x.shape}\n"
            coords_str += f"  * Mesh2_node_cart_y: {self.Mesh2_node_cart_y.shape}\n"
            coords_str += f"  * Mesh2_node_cart_z: {self.Mesh2_node_cart_z.shape}\n"
        if "Mesh2_face_x" in self._ds:
            coords_str += f"  * Mesh2_face_x: {self.Mesh2_face_x.shape}\n"
            coords_str += f"  * Mesh2_face_y: {self.Mesh2_face_y.shape}\n"

        connectivity_heading = "Grid Connectivity Variables:\n"
        connectivity_str = ""
        if "Mesh2_face_nodes" in self._ds:
            connectivity_str += f"  * Mesh2_face_nodes: {self.Mesh2_face_nodes.shape}\n"
        if "Mesh2_edge_nodes" in self._ds:
            connectivity_str += f"  * Mesh2_edge_nodes: {self.Mesh2_edge_nodes.shape}\n"
        if "Mesh2_face_edges" in self._ds:
            connectivity_str += f"  * Mesh2_face_edges: {self.Mesh2_face_edges.shape}\n"
        connectivity_str += f"  * nNodes_per_face: {self.nNodes_per_face.shape}\n"

        return prefix + original_grid_str + dims_heading + dims_str + coord_heading + coords_str + \
            connectivity_heading + connectivity_str

    def __eq__(self, other):
        """Two grids are equal if they have matching grid topology variables,
        coordinates, and dims all of which are equal.

        Parameters
        ----------
        other : uxarray.Grid
            The second grid object to be compared with `self`

        Returns
        -------
        If two grids are equal : bool
        """
        # TODO: deprecate grid var names
        if other is not None:
            # Iterate over dict to set access attributes
            for key, value in self.grid_var_names.items():
                # Check if all grid variables are equal
                if self._ds.data_vars is not None:
                    if value in self._ds.data_vars:
                        if not self._ds[value].equals(
                                other._ds[other.grid_var_names[key]]):
                            return False
        else:
            return False

        return True

    def __ne__(self, other):
        """Two grids are not equal if they have differing grid topology
        variables, coordinates, or dims.

        Parameters
        ----------
        other : uxarray.Grid
            The second grid object to be compared with `self`

        Returns
        -------
        If two grids are not equal : bool
        """
        return not self.__eq__(other)

    @property
    def parsed_attrs(self):
        """Dictionary of parsed attributes from the source grid."""
        return self._ds.attrs

    # TODO: Still need?
    # @property
    # def Mesh2(self):
    #     """UGRID Attribute ``Mesh2``, which indicates the topology data of a 2D
    #     unstructured mesh."""
    #     return self._ds[self.grid_var_names["Mesh2"]]

    @property
    def nMesh2_node(self):
        """UGRID Dimension ``nMesh2_node``, which represents the total number
        of nodes."""
        return self._ds["Mesh2_node_x"].shape[0]

    @property
    def nMesh2_face(self):
        """UGRID Dimension ``nMesh2_face``, which represents the total number
        of faces."""
        return self._ds["Mesh2_face_nodes"].shape[0]

    @property
    def nMesh2_edge(self):
        """UGRID Dimension ``nMesh2_edge``, which represents the total number
        of edges."""

        if "Mesh2_edge_nodes" not in self._ds:
            _build_edge_node_connectivity(self, repopulate=True)

        return self._ds['Mesh2_edge_nodes'].shape[0]

    @property
    def nMaxMesh2_face_nodes(self):
        """UGRID Dimension ``nMaxMesh2_face_nodes``, which represents the
        maximum number of faces nodes that a face may contain."""
        return self.Mesh2_face_nodes.shape[1]

    @property
    def nMaxMesh2_face_edges(self):
        """Dimension ``nMaxMesh2_face_edges``, which represents the maximum
        number of edges per face.

        Equivalent to ``nMaxMesh2_face_nodes``
        """

        if "Mesh2_face_edges" not in self._ds:
            _build_face_edges_connectivity(self)

        return self._ds["Mesh2_face_edges"].shape[1]

    @property
    def nNodes_per_face(self):
        """Dimension Variable ``nNodes_per_face``, which contains the number of
        non-fill-value nodes per face.

        Dimensions (``nMesh2_nodes``) and DataType ``INT_DTYPE``.
        """
        if "nNodes_per_face" not in self._ds:
            _build_nNodes_per_face(self)
        return self._ds["nNodes_per_face"]

    @property
    def Mesh2_node_x(self):
        """UGRID Coordinate Variable ``Mesh2_node_x``, which contains the
        longitude of each node in degrees.

        Dimensions (``nMesh2_node``)
        """
        return self._ds["Mesh2_node_x"]

    @property
    def Mesh2_node_cart_x(self):
        """Coordinate Variable ``Mesh2_node_cart_x``, which contains the x
        location in meters.

        Dimensions (``nMesh2_node``)
        """
        if "Mesh2_node_cart_x" not in self._ds:
            _populate_cartesian_xyz_coord(self)
        return self._ds['Mesh2_node_cart_x']

    @property
    def Mesh2_face_x(self):
        """UGRID Coordinate Variable ``Mesh2_face_x``, which contains the
        longitude of each face center.

        Dimensions (``nMesh2_face``)
        """
        if "Mesh2_face_x" in self._ds:
            return self._ds["Mesh2_face_x"]
        else:
            return None

    @property
    def Mesh2_node_y(self):
        """UGRID Coordinate Variable ``Mesh2_node_y``, which contains the
        latitude of each node.

        Dimensions (``nMesh2_node``)
        """
        return self._ds["Mesh2_node_y"]

    @property
    def Mesh2_node_cart_y(self):
        """Coordinate Variable ``Mesh2_node_cart_y``, which contains the y
        location in meters.

        Dimensions (``nMesh2_node``)
        """
        if "Mesh2_node_cart_y" not in self._ds:
            _populate_cartesian_xyz_coord(self)
        return self._ds['Mesh2_node_cart_y']

    @property
    def Mesh2_face_y(self):
        """UGRID Coordinate Variable ``Mesh2_face_y``, which contains the
        latitude of each face center.

        Dimensions (``nMesh2_face``)
        """
        if "Mesh2_face_y" in self._ds:
            return self._ds["Mesh2_face_y"]
        else:
            return None

    # TODO: Deprecate?
    # @property
    # def _Mesh2_node_z(self):
    #     """Coordinate Variable ``_Mesh2_node_z``, which contains the level of
    #     each node. It is only a placeholder for now as a protected attribute.
    #     UXarray does not support this yet and only handles the 2D flexibile
    #     meshes.
    #
    #     If we introduce handling of 3D meshes in the future, it might be only
    #     levels, i.e. the same level(s) for all nodes, instead of separate
    #     level for each node that ``_Mesh2_node_z`` suggests.
    #
    #     Dimensions (``nMesh2_node``)
    #     """
    #     if self.grid_var_names["Mesh2_node_z"] in self._ds:
    #         return self._ds[self.grid_var_names["Mesh2_node_z"]]
    #     else:
    #         return None

    @property
    def Mesh2_node_cart_z(self):
        """Coordinate Variable ``Mesh2_node_cart_z``, which contains the z
        location in meters.

        Dimensions (``nMesh2_node``)
        """
        if "Mesh2_node_cart_z" not in self._ds:
            self._populate_cartesian_xyz_coord()
        return self._ds['Mesh2_node_cart_z']

    @property
    def Mesh2_face_nodes(self):
        """UGRID Connectivity Variable ``Mesh2_face_nodes``, which maps each
        face to its corner nodes.

        Dimensions (``nMesh2_face``, ``nMaxMesh2_face_nodes``) and
        DataType ``INT_DTYPE``.

        Faces can have arbitrary length, with _FillValue=-1 used when faces
        have fewer nodes than MaxNumNodesPerFace.

        Nodes are in counter-clockwise order.
        """

        return self._ds["Mesh2_face_nodes"]

    @property
    def Mesh2_edge_nodes(self):
        """UGRID Connectivity Variable ``Mesh2_edge_nodes``, which maps every
        edge to the two nodes that it connects.

        Dimensions (``nMesh2_edge``, ``Two``) and DataType
        ``INT_DTYPE``.

        Nodes are in arbitrary order.
        """
        if "Mesh2_edge_nodes" not in self._ds:
            _build_edge_node_connectivity(self)

        return self._ds['Mesh2_edge_nodes']

    @property
    def Mesh2_face_edges(self):
        """UGRID Connectivity Variable ``Mesh2_face_edges``, which maps every
        face to its edges.

        Dimensions (``nMesh2_face``, ``nMaxMesh2_face_nodes``) and
        DataType ``INT_DTYPE``.
        """
        if "Mesh2_face_edges" not in self._ds:
            _build_face_edges_connectivity(self)

        return self._ds["Mesh2_face_edges"]

    # other properties
    @property
    def antimeridian_face_indices(self):
        """Index of each face that crosses the antimeridian."""
        if self._antimeridian_face_indices is None:
            self._antimeridian_face_indices = _build_antimeridian_face_indices(
                self)
        return self._antimeridian_face_indices

    @property
    def face_areas(self):
        """Declare face_areas as a property."""
        # if self._face_areas is not None: it allows for using the cached result
        if self._face_areas is None:
            self.compute_face_areas()
        return self._face_areas

    def copy(self):
        """Returns a deep copy of this grid."""
        return Grid(xr.Dataset(self._ds),
                    gridspec=self.gridspec,
                    vertices=self.vertices,
                    islatlon=self.islatlon,
                    isconcave=self.isconcave,
                    source_grid=self.source_grid,
                    use_dual=self.use_dual)

    def encode_as(self, grid_type):
        """Encodes the grid as a new `xarray.Dataset` per grid format supplied
        in the `grid_type` argument.

        Parameters
        ----------
        grid_type : str, required
            Grid type of output dataset.
            Currently supported options are "ugrid", "exodus", and "scrip"

        Returns
        -------
        out_ds : xarray.Dataset
            The output `xarray.Dataset` that is encoded from the this grid.

        Raises
        ------
        RuntimeError
            If provided grid type or file type is unsupported.
        """

        if grid_type == "ugrid":
            out_ds = _encode_ugrid(self._ds)

        elif grid_type == "exodus":
            out_ds = _encode_exodus(self._ds, self.grid_var_names)

        elif grid_type == "scrip":
            out_ds = _encode_scrip(self.Mesh2_face_nodes, self.Mesh2_node_x,
                                   self.Mesh2_node_y, self.face_areas)
        else:
            raise RuntimeError("The grid type not supported: ", grid_type)

        return out_ds

    def calculate_total_face_area(self, quadrature_rule="triangular", order=4):
        """Function to calculate the total surface area of all the faces in a
        mesh.

        Parameters
        ----------
        quadrature_rule : str, optional
            Quadrature rule to use. Defaults to "triangular".
        order : int, optional
            Order of quadrature rule. Defaults to 4.

        Returns
        -------
        Sum of area of all the faces in the mesh : float
        """

        # call function to get area of all the faces as a np array
        face_areas = self.compute_face_areas(quadrature_rule, order)

        return np.sum(face_areas)

    def compute_face_areas(self, quadrature_rule="triangular", order=4):
        """Face areas calculation function for grid class, calculates area of
        all faces in the grid.

        Parameters
        ----------
        quadrature_rule : str, optional
            Quadrature rule to use. Defaults to "triangular".
        order : int, optional
            Order of quadrature rule. Defaults to 4.

        Returns
        -------
        Area of all the faces in the mesh : np.ndarray

        Examples
        --------
        Open a uxarray grid file

        >>> grid = ux.open_dataset("/home/jain/uxarray/test/meshfiles/ugrid/outCSne30/outCSne30.ug")

        Get area of all faces in the same order as listed in grid._ds.Mesh2_face_nodes

        >>> grid.face_areas
        array([0.00211174, 0.00211221, 0.00210723, ..., 0.00210723, 0.00211221,
            0.00211174])
        """
        # if self._face_areas is None: # this allows for using the cached result,
        # but is not the expected behavior behavior as we are in need to recompute if this function is called with different quadrature_rule or order

        # area of a face call needs the units for coordinate conversion if spherical grid is used
        coords_type = "spherical"
        if not "degree" in self.Mesh2_node_x.units:
            coords_type = "cartesian"

        face_nodes = self.Mesh2_face_nodes.data
        nNodes_per_face = self.nNodes_per_face.data
        dim = self.Mesh2.attrs['topology_dimension']

        # initialize z
        z = np.zeros((self.nMesh2_node))

        # call func to cal face area of all nodes
        x = self.Mesh2_node_x.data
        y = self.Mesh2_node_y.data
        # check if z dimension
        if self.Mesh2.topology_dimension > 2:
            z = self._Mesh2_node_z.data

        # Note: x, y, z are np arrays of type float
        # Using np.issubdtype to check if the type is float
        # if not (int etc.), convert to float, this is to avoid numba errors
        x, y, z = (arr.astype(float)
                   if not np.issubdtype(arr[0], np.floating) else arr
                   for arr in (x, y, z))

        # call function to get area of all the faces as a np array
        self._face_areas = get_all_face_area_from_coords(
            x, y, z, face_nodes, nNodes_per_face, dim, quadrature_rule, order,
            coords_type)

        return self._face_areas

    # TODO: Make a decision on whether to provide Dataset- or DataArray-specific
    # functions from within Grid
    # def integrate(self, var_ds, quadrature_rule="triangular", order=4):
    #     """Integrates a xarray.Dataset over all the faces of the given mesh.
    #
    #     Parameters
    #     ----------
    #     var_ds : Xarray dataset, required
    #         Xarray dataset containing values to integrate on this grid
    #     quadrature_rule : str, optional
    #         Quadrature rule to use. Defaults to "triangular".
    #     order : int, optional
    #         Order of quadrature rule. Defaults to 4.
    #
    #     Returns
    #     -------
    #     Calculated integral : float
    #
    #     Examples
    #     --------
    #     Open grid file only
    #
    #     >>> xr_grid = xr.open_dataset("grid.ug")
    #     >>> grid = ux.Grid.(xr_grid)
    #     >>> var_ds = xr.open_dataset("centroid_pressure_data_ug")
    #
    #     # Compute the integral
    #     >>> integral_psi = grid.integrate(var_ds)
    #     """
    #     integral = 0.0
    #
    #     # call function to get area of all the faces as a np array
    #     face_areas = self.compute_face_areas(quadrature_rule, order)
    #
    #     var_key = list(var_ds.keys())
    #     if len(var_key) > 1:
    #         # warning: print message
    #         print(
    #             "WARNING: The xarray dataset file has more than one variable, using the first variable for integration"
    #         )
    #     var_key = var_key[0]
    #     face_vals = var_ds[var_key].to_numpy()
    #     integral = np.dot(face_areas, face_vals)
    #
    #     return integral

    def to_geodataframe(self,
                        override=False,
                        cache=True,
                        correct_antimeridian_polygons=True):
        """Constructs a ``spatialpandas.GeoDataFrame`` with a "geometry"
        column, containing a collection of Shapely Polygons or MultiPolygons
        representing the geometry of the unstructured grid. Additionally, any
        polygon that crosses the antimeridian is split into MultiPolygons.

        Parameters
        ----------
        override : bool
            Flag to recompute the ``GeoDataFrame`` if one is already cached
        cache : bool
            Flag to indicate if the computed ``GeoDataFrame`` should be cached
        correct_antimeridian_polygons: bool, Optional
            Parameter to select whether to correct and split antimeridian polygons

        Returns
        -------
        gdf : spatialpandas.GeoDataFrame
            The output `GeoDataFrame` with a filled out "geometry" collumn
        """

        # use cached geodataframe
        if self._gdf is not None and not override:
            return self._gdf

        # construct a geodataframe with the faces stored as polygons as the geometry
        gdf = _grid_to_polygon_geodataframe(self, correct_antimeridian_polygons)

        # cache computed geodataframe
        if cache:
            self._gdf = gdf

        return gdf

    def to_polycollection(self,
                          override=False,
                          cache=True,
                          correct_antimeridian_polygons=True):
        """Constructs a ``matplotlib.collections.PolyCollection`` object with
        polygons representing the geometry of the unstructured grid, with
        polygons that cross the antimeridian split.

        Parameters
        ----------
        override : bool
            Flag to recompute the ``PolyCollection`` if one is already cached
        cache : bool
            Flag to indicate if the computed ``PolyCollection`` should be cached

        Returns
        -------
        polycollection : matplotlib.collections.PolyCollection
            The output `PolyCollection` containing faces represented as polygons
        corrected_to_original_faces: list
            Original indices used to map the corrected polygon shells to their entries in face nodes
        """

        # use cached polycollection
        if self._poly_collection is not None and not override:
            return self._poly_collection

        poly_collection, corrected_to_original_faces = _grid_to_matplotlib_polycollection(
            self)

        # cache computed polycollection
        if cache:
            self._poly_collection = poly_collection

        return poly_collection, corrected_to_original_faces

    def to_shapely_polygons(self, correct_antimeridian_polygons=True):
        """Constructs an array of Shapely Polygons representing each face, with
        antimeridian polygons split according to the GeoJSON standards.

         Parameters
        ----------
        correct_antimeridian_polygons: bool, Optional
            Parameter to select whether to correct and split antimeridian polygons

        Returns
        -------
        polygons : np.ndarray
            Array containing Shapely Polygons
        """
        polygons = _grid_to_polygons(self, correct_antimeridian_polygons)
        return polygons
