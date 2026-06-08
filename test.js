
//
//  David Hall. U.S.D.A. Forest Service, Rocky Mountain Research Station
//
//  28 December 2000 add link to DMS <--> decimal degrees calculator
var browserName=navigator.appName;
var browserVer=parseInt(navigator.appVersion);

function load_latlon(obj)
{
    if (self.creator.document.prism.platitude) {
       obj.baselat.value=self.creator.document.prism.platitude.value
    }
    if (self.creator.document.prism.plongitude) {
       obj.baselon.value=-self.creator.document.prism.plongitude.value
    }
    newLatLong();
}
function apply_latlon(obj)
{
//  alert('applying...')
    if (self.creator.document.prism.platitude) {
       self.creator.document.prism.platitude.value=obj.newlat.value
    }
    if (self.creator.document.prism.plongitude) {
       self.creator.document.prism.plongitude.value=-obj.newlon.value
    }
  window.close(self);
}

function newLongitude() {
  // Length of 1 degree of longitude = cosine(latitude) * [length of degree at equator (in kilometers)]
  // www.colorado.edu/geography/gcraft/warmup/aquifer/html/distance.html [12/5/2000]
  // if (isNumber()) {}

  var lode = 69.172 * 1.6093    // [length of degree at equator (in kilometers)]
  var torads = Math.PI / 180    // factor for degrees to radians
  var kilometersEast=parseFloat(document.latlongkm.kilometersE.value)
  var baselatitude=parseFloat(document.latlongkm.baselat.value)
  var baselongitude=parseFloat(document.latlongkm.baselon.value)
  var onedegreelong=Math.cos(baselatitude*torads)*lode
  var deltalongitude=kilometersEast/onedegreelong
  var newlongitude=round(baselongitude+deltalongitude,5)
//  document.latlongkm.onedegree.value=onedegreelong
//  document.latlongkm.deltalon.value=deltalongitude
  document.latlongkm.newlon.value=newlongitude
}

function newLatitude() {
  // Length of 1 degree of latitude ranges from
  //    68.70 miles at  0 deg N to
  //    68.83          25 deg N (tip of Florida not including the Keys)
  //    69.12          50 deg N (approximate US/Canada border)   (range = 0.29 mile = 1531 feet = 510 yards)
  //    69.41 miles at 90 deg N (Compton's Encyclopedia Online v.3.0 www.comptons.com/encyclopedia/TABLES/150995113_T.html)
  //    68.703 miles at equator to 69.407 at poles due to earth's slightly ellipsoid shape)
  // "What is the distance between a degree of latitude and longitude?"
  // www.geography.about.com/science/geography/library/faq/blqzdistancedegree.htm cached 12/05/00
  var onedegreelat = 68.875 * 1.6093    // length of degree latitude (average between 25 deg N and 50 deg N)
  var kilometersNorth=parseFloat(document.latlongkm.kilometersN.value)
  var baselatitude=parseFloat(document.latlongkm.baselat.value)
  var deltalatitude=kilometersNorth/onedegreelat
  var newlatitude=round(baselatitude+deltalatitude,5)
  document.latlongkm.newlat.value=newlatitude
}
function newLatLong() {
  newLatitude()
  newLongitude()
}
function round(realnumber,numdecs) {
  var x = realnumber
  var cnumdecs = Math.round(numdecs)
  var factor = Math.pow(10,cnumdecs)
  var intermed = x * factor + 0.5
  var r = Math.floor(intermed) / factor
  return r
}
